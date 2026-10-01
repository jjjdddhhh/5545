# subtitles.py : 5a단계 자막 분할과 타이밍(설계서 4절). LLM을 부르지 않고 코드로만 한다(결정 2).
# 규칙
# 1. 한 줄은 설정 글자 수(기본 16자) 이하, 한 자막(큐)은 최대 2줄이다. 줄 길이는 공백을 포함해 센다(화면 폭 기준).
# 2. 단어(띄어쓰기 단위) 중간에서 끊지 않는다. 단어 하나가 한 줄보다 길 때만 어쩔 수 없이 글자 단위로 자른다.
# 3. 한 큐가 두 문장에 걸치지 않게 문장마다 따로 나눈다. 문장이 바뀌는 곳에서 화면 자막도 바뀌어야 읽기 쉽다.
# 4. 한 문장이 큐 여러 개가 되면 큐끼리 길이가 고르게 나누고(한 단어짜리 꼬리 큐 방지),
#    두 줄짜리 큐는 두 줄의 길이가 비슷하도록 끊는 자리를 다시 고른다(예: 15자+3자 대신 9자+9자).
# 5. 장면 시간을 큐마다 글자 수(공백 제외)에 비례해 나눈다. 마지막 큐는 장면 끝에서 정확히 끝난다(검수 C07).
# 수정 요청 에이전트의 split_subtitles(자막 미리보기)와 PATCH /api/narrations가 모두 이 파일의 함수를 쓴다.
import re

from app import config

# 문장 끝 판단: 마침표·물음표·느낌표 뒤의 공백에서 자른다. 마침표 없이 쓴 내레이션도 있으므로
# "~다 ", "~요 " 뒤에서도 자른다(text_cleaner의 받아쓰기 원고 규칙과 같은 생각이다).
_SENT_SPLIT = re.compile(r"(?<=[.!?。…])\s+")
_SENT_SPLIT_LOOSE = re.compile(r"(?<=[다요죠까])\s+")


def split_sentences(text: str) -> list[str]:
    """내레이션을 문장 목록으로 나눈다. 공백은 한 칸으로 정리한다."""
    text = re.sub(r"\s+", " ", text or "").strip()
    if not text:
        return []
    sents = _SENT_SPLIT.split(text)
    if len(sents) == 1:                       # 마침표가 하나도 없으면 어미에서 자른다
        sents = _SENT_SPLIT_LOOSE.split(text)
    return [s.strip() for s in sents if s.strip()]


def _words(sentence: str, max_chars: int) -> list[str]:
    """띄어쓰기 단위 단어 목록. 한 줄보다 긴 단어(긴 영문 주소 등)만 max_chars 크기로 자른다."""
    out = []
    for w in sentence.split(" "):
        while len(w) > max_chars:
            out.append(w[:max_chars])
            w = w[max_chars:]
        if w:
            out.append(w)
    return out


def _wrap(words: list[str], max_chars: int) -> list[list[str]]:
    """단어를 앞에서부터 한 줄(max_chars)에 들어가는 만큼 채운다. 줄마다 단어 목록을 돌려준다."""
    lines: list[list[str]] = []
    cur: list[str] = []
    for w in words:
        if cur and len(" ".join(cur + [w])) > max_chars:
            lines.append(cur)
            cur = [w]
        else:
            cur.append(w)
    if cur:
        lines.append(cur)
    return lines


def _balance(words: list[str], max_chars: int) -> list[str]:
    """두 줄 큐의 단어들을 두 줄로 다시 끊는다. 두 줄 모두 max_chars 이하인 끊는 자리 가운데
    두 줄 길이 차이가 가장 작은 곳을 고른다. 그런 자리가 없으면(이론상 생기지 않는다) 앞에서부터 채운 결과를 쓴다."""
    best = None
    for k in range(1, len(words)):
        a, b = " ".join(words[:k]), " ".join(words[k:])
        if len(a) <= max_chars and len(b) <= max_chars:
            diff = abs(len(a) - len(b))
            if best is None or diff < best[0]:
                best = (diff, a, b)
    if best is None:
        return [" ".join(line) for line in _wrap(words, max_chars)]
    return [best[1], best[2]]


def _fits(words: list[str], max_chars: int, max_lines: int) -> bool:
    """단어 묶음이 큐 하나(max_lines줄)에 들어가는지."""
    return len(_wrap(words, max_chars)) <= max_lines


def _partition(words: list[str], max_chars: int, max_lines: int) -> list[list[str]]:
    """한 문장의 단어들을 큐 여러 개로 나눈다. 큐 수는 앞에서부터 채웠을 때와 같게(가장 적게) 두되,
    큐마다 글자 수가 고르도록 끊는 자리를 고른다. 앞에서부터 채우기만 하면 "주세요." 같은 한 단어짜리
    꼬리 큐가 생겨 화면에 너무 짧게 스쳐 지나가기 때문이다.
    방법: 동적 계획법으로 "큐 k개로 나눴을 때 가장 긴 큐의 글자 수"가 가장 작은 나눔을 찾는다.
    한 문장의 단어는 많아야 수십 개라 계산량은 무시할 만하다."""
    greedy = _wrap(words, max_chars)
    k = -(-len(greedy) // max_lines)               # 앞에서부터 채웠을 때의 큐 수(올림 나눗셈)
    if k <= 1:
        return [words]
    n = len(words)
    INF = float("inf")
    length = lambda i, j: len(" ".join(words[i:j]))
    # best[c][j]: 앞의 j개 단어를 큐 c개로 나눴을 때 가장 긴 큐의 길이. cut[c][j]: 그때 마지막 큐가 시작하는 단어 위치.
    best = [[INF] * (n + 1) for _ in range(k + 1)]
    cut = [[0] * (n + 1) for _ in range(k + 1)]
    best[0][0] = 0
    for c in range(1, k + 1):
        for j in range(1, n + 1):
            for i in range(c - 1, j):
                if best[c - 1][i] == INF or not _fits(words[i:j], max_chars, max_lines):
                    continue
                cand = max(best[c - 1][i], length(i, j))
                if cand < best[c][j]:
                    best[c][j], cut[c][j] = cand, i
    if best[k][n] == INF:                          # 이론상 생기지 않지만, 생기면 앞에서부터 채운 결과를 쓴다
        return [[w for line in greedy[i:i + max_lines] for w in line] for i in range(0, len(greedy), max_lines)]
    parts, j = [], n
    for c in range(k, 0, -1):
        i = cut[c][j]
        parts.append(words[i:j])
        j = i
    return parts[::-1]


def split_subtitles(text: str, max_chars: int = config.SUBTITLE_MAX_CHARS,
                    max_lines: int = config.SUBTITLE_MAX_LINES) -> list[str]:
    """내레이션을 자막 큐 본문 목록으로 나눈다. 큐 본문은 줄바꿈("\\n")으로 이은 최대 max_lines줄이다.
    예(16자 기준): "비트는 척에 깊이 넣고 척 키로 세 군데를 고르게 조여 주세요."
        -> ["비트는 척에 깊이\\n넣고 척 키로", "세 군데를 고르게\\n조여 주세요."]"""
    cues: list[str] = []
    for sent in split_sentences(text):
        for part in _partition(_words(sent, max_chars), max_chars, max_lines):
            lines = _wrap(part, max_chars)
            if len(lines) == 2:                    # 두 줄이면 두 줄 길이가 비슷하게 다시 끊는다
                cues.append("\n".join(_balance(part, max_chars)))
            else:
                cues.append("\n".join(" ".join(line) for line in lines))
    return cues


def _weight(body: str) -> int:
    """타이밍 배분의 무게. 읽는 시간은 공백을 뺀 글자 수에 비례한다고 본다. 최소 1로 두어 0초 큐가 생기지 않게 한다."""
    return max(1, sum(1 for ch in body if not ch.isspace()))


def time_cues(bodies: list[str], duration_ms: int) -> list[tuple[int, int]]:
    """장면 시간(ms)을 큐마다 글자 수에 비례해 나눈다. 누적 글자 수로 경계를 계산해 반올림 오차가 쌓이지 않게 하고,
    마지막 경계는 정확히 duration_ms다. 큐마다 끝이 시작보다 1ms 이상 뒤에 오도록 보정한다(subtitle_cue CHECK 제약)."""
    if not bodies:
        return []
    duration_ms = max(duration_ms, len(bodies))   # 큐마다 최소 1ms는 있어야 CHECK (end_ms > start_ms)를 지킨다
    weights = [_weight(b) for b in bodies]
    total = sum(weights)
    bounds, acc = [0], 0
    for w in weights:
        acc += w
        bounds.append(round(duration_ms * acc / total))
    bounds[-1] = duration_ms
    for i in range(1, len(bounds)):               # 경계가 겹치면 1ms씩 밀어 엄격히 증가하게 만든다
        if bounds[i] <= bounds[i - 1]:
            bounds[i] = bounds[i - 1] + 1
    if bounds[-1] > duration_ms:                  # 밀다가 끝을 넘으면 뒤에서부터 당겨 끝을 맞춘다
        bounds[-1] = duration_ms
        for i in range(len(bounds) - 2, 0, -1):
            if bounds[i] >= bounds[i + 1]:
                bounds[i] = bounds[i + 1] - 1
    return [(bounds[i], bounds[i + 1]) for i in range(len(bodies))]


def build_cues(text: str, duration_sec: int, max_chars: int = config.SUBTITLE_MAX_CHARS,
               max_lines: int = config.SUBTITLE_MAX_LINES) -> list[dict]:
    """내레이션 하나를 subtitle_cue 행 모양의 목록으로 만든다. 시간은 장면 시작 기준(ms)이다."""
    bodies = split_subtitles(text, max_chars, max_lines)
    return [{"seq": i, "start_ms": s, "end_ms": e, "body": body}
            for i, (body, (s, e)) in enumerate(zip(bodies, time_cues(bodies, duration_sec * 1000)), 1)]
