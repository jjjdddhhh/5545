# checks.py : 6단계 검수(설계서 10절). 모든 검사는 코드로 하며 LLM을 부르지 않는다.
# 이 파일의 검사 함수는 DB를 모르는 순수 함수다. 딕셔너리와 문자열을 받아 CheckResult 목록을 돌려준다.
# 그래서 DB 없이 단위 테스트할 수 있고, 생성 단계(바로 다시 요청할지 판단), 6단계(결과 저장),
# 수정 요청 에이전트(제안 검수)가 같은 함수를 함께 쓴다.
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from app import config
from app.pipeline import budget as budget_mod

PASS, WARN, FAIL = "pass", "warn", "fail"


@dataclass
class CheckResult:
    code: str                          # C01~C12
    result: str                        # pass, warn, fail (저장할 때 정책에 따라 fail이 warn으로 바뀔 수 있다)
    message: str = ""                  # 사람이 읽을 설명. review_check.message VARCHAR(500)에 맞춰 자른다
    target_type: Optional[str] = None  # scene, narration, subtitle, manual, manual_step, schedule, outline, run
    target_ref: Optional[int] = None   # 대상 식별값. 생성 중에는 장면·단계 순서(seq), 저장 뒤에는 DB id를 쓴다
    data: dict = field(default_factory=dict)   # 재요청 문장을 만들 때 쓰는 세부 정보(예: 틀린 문단 번호)

    @property
    def failed(self) -> bool:
        return self.result == FAIL


# ---------- C02 장면 수 ----------
def check_scene_count(scene_count: int, expected: int) -> CheckResult:
    """C02: 구성안의 장면 수가 분량 계산 결과와 같은지. 실패하면 구성안 단계를 1회 다시 요청한다."""
    if scene_count == expected:
        return CheckResult("C02", PASS, f"장면 수 {scene_count}개가 분량 계산 결과와 같습니다.", "outline")
    return CheckResult("C02", FAIL, f"장면 수가 {scene_count}개입니다. 분량 계산 결과는 {expected}개입니다.",
                       "outline", data={"got": scene_count, "expected": expected})


# ---------- C03 근거 문단 ----------
def check_sources(items: list[dict], paragraph_ids: set[str], target_type: str = "scene") -> list[CheckResult]:
    """C03: 모든 장면(또는 매뉴얼 단계)에 근거 문단이 있고, 그 번호가 실제 문단 목록에 있는지.
    items의 각 원소는 {"seq": 순서, "source_paragraphs": [...], "id": (있으면 DB id)} 모양이다.
    대상마다 결과를 하나씩 돌려줘, 어느 장면이 틀렸는지 장면 목록의 점 색으로 보여 줄 수 있게 한다."""
    out = []
    for it in items:
        ref = it.get("id", it.get("seq"))
        ids = list(it.get("source_paragraphs") or [])
        unknown = [p for p in ids if p not in paragraph_ids]
        label = "장면" if target_type == "scene" else "단계"
        if not ids:
            out.append(CheckResult("C03", FAIL, f"{label} {it.get('seq')}에 근거 문단이 없습니다.", target_type, ref,
                                   {"seq": it.get("seq"), "missing": True}))
        elif unknown:
            out.append(CheckResult("C03", FAIL,
                                   f"{label} {it.get('seq')}의 근거 문단 {', '.join(unknown)}이(가) 원고에 없습니다.",
                                   target_type, ref, {"seq": it.get("seq"), "unknown": unknown}))
        else:
            out.append(CheckResult("C03", PASS, f"근거 문단 {', '.join(ids)}", target_type, ref))
    return out


# ---------- C11 출력 언어 ----------
HANGUL = re.compile(r"[가-힣ㄱ-ㆎ]")         # 완성형 한글과 자모
LATIN = re.compile(r"[A-Za-z]")
KANA = re.compile(r"[぀-ヿ]")                         # 히라가나와 가타카나
HAN = re.compile(r"[一-鿿]")                          # 한자
# 한국어 결과에도 "LED", "rpm" 같은 영문 용어가 섞이므로, 한글이 글자의 60% 이상이면 한국어로 본다.
# 영어 결과는 고유명사로 한글이 섞일 일이 거의 없어 라틴 문자 80% 이상을 기준으로 잡았다.
LANG_MIN_RATIO = {"ko": 0.6, "en": 0.8, "ja": 0.5, "zh": 0.6}
# 비율을 믿을 수 있는 최소 글자 수. "OK" 같은 아주 짧은 글은 비율이 의미가 없어 통과로 본다.
LANG_MIN_LETTERS = 10


def language_ratio(text: str, language: str) -> Optional[float]:
    """글자(숫자, 기호, 공백 제외) 가운데 그 언어의 문자가 차지하는 비율. 검사 규칙이 없는 언어면 None."""
    counts = {"ko": len(HANGUL.findall(text)), "en": len(LATIN.findall(text)),
              "kana": len(KANA.findall(text)), "han": len(HAN.findall(text))}
    letters = sum(counts.values())
    if letters < LANG_MIN_LETTERS:
        return 1.0
    if language == "ko":
        return counts["ko"] / letters
    if language == "en":
        return counts["en"] / letters
    if language == "ja":
        return (counts["kana"] + counts["han"]) / letters   # 일본어는 가나와 한자를 함께 쓴다
    if language == "zh":
        return counts["han"] / letters
    return None


def check_language(text: str, language: str, target_type: str, target_ref: Optional[int] = None) -> CheckResult:
    """C11: 출력 언어가 설정한 언어와 같은지 문자 종류의 비율로 확인한다."""
    ratio = language_ratio(text, language)
    if ratio is None:
        return CheckResult("C11", PASS, f"'{language}'은(는) 문자 비율 검사 규칙이 없어 확인하지 않았습니다.",
                           target_type, target_ref)
    need = LANG_MIN_RATIO[language]
    if ratio >= need:
        return CheckResult("C11", PASS, f"설정 언어 문자 비율 {ratio:.0%}", target_type, target_ref)
    return CheckResult("C11", FAIL, f"설정 언어({language}) 문자 비율이 {ratio:.0%}로 기준 {need:.0%}보다 낮습니다.",
                       target_type, target_ref, {"ratio": ratio})


def feedback_text(results: list[CheckResult]) -> str:
    """실패한 검사 결과를 LLM에게 다시 요청할 때 붙일 문장으로 바꾼다(llm_step.call_llm의 feedback)."""
    return "\n".join(f"- {r.message}" for r in results if r.failed)


# ---------- C08 수치와 단위 ----------
# 문장 속 "숫자+단위"를 뽑는다. 단위 목록은 교육·안전 원고에 자주 나오는 것으로 채웠고, 같은 글자로 시작하는
# 단위는 긴 것을 앞에 두어(mm가 m보다 앞) 짧은 단위가 먼저 잡히지 않게 했다.
_UNITS = ("°C", "℃", "퍼센트", "%", "시간", "주일", "개월", "초", "분", "일", "주", "달", "년", "회", "번", "개", "장",
          "대", "명", "곳", "군데", "mm", "cm", "km", "kg", "mg", "ml", "mL", "kW", "rpm", "Nm", "bar", "psi",
          "m", "g", "L", "V", "W", "A", "도")
NUM_UNIT = re.compile(r"(\d+(?:[.,]\d+)*)\s*(" + "|".join(re.escape(u) for u in _UNITS) + r")?(?![A-Za-z])")
# 같은 뜻의 단위는 하나로 맞춘다. "3℃"와 "3°C", "2주일"과 "2주"는 같은 값으로 본다.
_UNIT_ALIAS = {"℃": "°C", "퍼센트": "%", "주일": "주", "달": "개월", "mL": "ml", "곳": "군데"}
# 순서를 뜻하는 숫자는 수치가 아니므로 대조하지 않는다. 예: "2단계에서", "3번째", "장면 4"
_ORDINAL_AFTER = re.compile(r"^\s*(단계|번째|째|장면|항목|절|장\b)")


def extract_numbers(text: str) -> list[tuple[str, str]]:
    """문장에서 (값, 단위) 목록을 뽑는다. 값의 천 단위 쉼표는 지우고("1,000" -> "1000"), 단위가 없으면 ""이다."""
    out = []
    for mt in NUM_UNIT.finditer(text or ""):
        value, unit = mt.group(1), mt.group(2) or ""
        if _ORDINAL_AFTER.match(text[mt.end(1):]):
            continue
        if re.fullmatch(r"\d{1,3}(,\d{3})+", value):   # 천 단위 쉼표만 지운다. "1,5" 같은 소수 쉼표는 그대로 둔다
            value = value.replace(",", "")
        out.append((value, _UNIT_ALIAS.get(unit, unit)))
    return out


def unsupported_numbers(text: str, evidence: str) -> list[str]:
    """text의 수치 가운데 evidence(근거 원문)에 없는 것을 "값+단위" 문자열로 돌려준다.
    단위가 있으면 값과 단위가 함께 원문에 있어야 하고, 단위가 없으면 값만 원문에 있으면 된다."""
    have = set(extract_numbers(evidence))
    have_values = {v for v, _ in have}
    missing = []
    for value, unit in extract_numbers(text):
        ok = (value, unit) in have if unit else value in have_values
        if not ok:
            missing.append(f"{value}{unit}")
    return list(dict.fromkeys(missing))


def check_numbers(text: str, evidence: str, target_type: str, target_ref=None, label: str = "") -> CheckResult:
    """C08: 매뉴얼 문장 속 수치와 단위가 모두 근거 원문에 있는지(설계서 9절 마지막 문단)."""
    missing = unsupported_numbers(text, evidence)
    if not missing:
        return CheckResult("C08", PASS, "수치가 모두 원고와 일치합니다.", target_type, target_ref)
    return CheckResult("C08", FAIL, f"{label}원고에 없는 수치가 있습니다: {', '.join(missing)}", target_type, target_ref,
                       {"missing": missing})


# ---------- C09 일정 배치 ----------
def check_schedule(items: list[dict]) -> CheckResult:
    """C09: 일정 항목이 매뉴얼 단계 순서대로 이어서 배치되고 기간이 1일 이상인지.
    items는 매뉴얼 단계 순서로 정렬된 [{"step_seq", "start_offset_day", "duration_days"}, ...]이다.
    실패하면 일정을 코드로 다시 배치한다(schedule.layout)."""
    expected = 0
    for it in items:
        if it["duration_days"] < 1:
            return CheckResult("C09", FAIL, f"'{it.get('title', '')}' 일정의 기간이 1일보다 짧습니다.", "manual")
        if it["start_offset_day"] != expected:
            return CheckResult("C09", FAIL, f"'{it.get('title', '')}' 일정이 매뉴얼 단계 순서와 맞지 않습니다.", "manual")
        expected = it["start_offset_day"] + it["duration_days"]
    return CheckResult("C09", PASS, f"일정 {len(items)}개가 단계 순서대로 배치되었습니다.", "manual")


# ---------- 표현 사전 읽기 ----------
RULES_DIR = Path(__file__).resolve().parents[1] / "rules"


def load_terms(name: str) -> list[str]:
    """app/rules/의 표현 목록을 읽는다. 호출할 때마다 파일을 다시 읽어, 서버를 다시 켜지 않아도 고친 목록이 바로 쓰이게 한다.
    목록이 수십 줄이라 매번 읽어도 비용이 거의 없다."""
    path = RULES_DIR / name
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return [ln.strip() for ln in lines if ln.strip() and not ln.strip().startswith("#")]


# ---------- C04 내레이션 글자 수 ----------
def check_budget(text: str, budget: int, target_type: str = "narration", ref=None,
                 tolerance: float = config.NARRATION_TOLERANCE) -> CheckResult:
    """C04: 내레이션 글자 수(공백 제외)가 장면 예산의 ±허용 오차 안에 있는지. 실패하면 그 장면의 내레이션만 다시 요청한다."""
    n = budget_mod.count_chars(text)
    lo, hi = int(budget * (1 - tolerance) + 0.999), int(budget * (1 + tolerance))   # 허용 범위를 정수 글자 수로
    if budget_mod.within_tolerance(n, budget, tolerance):
        return CheckResult("C04", PASS, f"{n}자 (예산 {budget}자, 허용 {lo}~{hi}자)", target_type, ref)
    side = "깁니다" if n > budget else "짧습니다"
    return CheckResult("C04", FAIL, f"내레이션이 {n}자로 {side}. 공백을 빼고 {lo}~{hi}자(예산 {budget}자)로 맞춰야 합니다.",
                       target_type, ref, {"chars": n, "budget": budget, "min": lo, "max": hi})


# ---------- C05 강조 키워드 ----------
def check_keywords(keywords: list[str], all_text: str) -> CheckResult:
    """C05: 강조 키워드가 결과 어딘가에 들어 있는지. 띄어쓰기 차이("보호 장갑"과 "보호장갑")는 같은 것으로 본다.
    빠져도 경고만 한다(설계서 10절)."""
    squashed = re.sub(r"\s+", "", all_text).lower()
    missing = [k for k in keywords if re.sub(r"\s+", "", k).lower() not in squashed]
    if not keywords:
        return CheckResult("C05", PASS, "강조 키워드가 없습니다.", "run")
    if missing:
        return CheckResult("C05", WARN, f"키워드 누락 {len(missing)}건: {', '.join(missing)}", "run",
                           data={"missing": missing})
    return CheckResult("C05", PASS, f"키워드 {len(keywords)}개가 모두 들어 있습니다.", "run")


# ---------- C06 자막 줄 길이와 줄 수 ----------
def check_subtitle_lines(cues: list[dict], max_chars: int, ref=None,
                         max_lines: int = config.SUBTITLE_MAX_LINES) -> CheckResult:
    """C06: 자막 한 줄이 설정 글자 수 이하이고 큐마다 최대 2줄인지. 실패하면 자막을 자동으로 다시 나눈다."""
    for c in cues:
        lines = c["body"].split("\n")
        if len(lines) > max_lines:
            return CheckResult("C06", FAIL, f"자막 {c.get('seq', '')}이(가) {len(lines)}줄입니다.", "subtitle", ref)
        long = [ln for ln in lines if len(ln) > max_chars]
        if long:
            return CheckResult("C06", FAIL, f"자막 한 줄이 {len(long[0])}자로 {max_chars}자를 넘습니다: {long[0]}",
                               "subtitle", ref)
    return CheckResult("C06", PASS, f"자막 {len(cues)}개가 줄 길이 기준을 지킵니다.", "subtitle", ref)


# ---------- C07 자막 시간 ----------
def check_subtitle_timing(cues: list[dict], duration_sec: int, ref=None) -> CheckResult:
    """C07: 자막 시간이 겹치지 않고, 0부터 시작해 장면 시간에서 끝나는지. 실패하면 타이밍을 자동으로 다시 계산한다."""
    if not cues:
        return CheckResult("C07", FAIL, "자막이 없습니다.", "subtitle", ref)
    cues = sorted(cues, key=lambda c: c.get("seq", 0))
    prev_end = 0
    for i, c in enumerate(cues):
        if c["end_ms"] <= c["start_ms"]:
            return CheckResult("C07", FAIL, f"자막 {i + 1}의 끝 시각이 시작보다 빠릅니다.", "subtitle", ref)
        if i == 0 and c["start_ms"] != 0:
            return CheckResult("C07", FAIL, "첫 자막이 장면 시작에서 시작하지 않습니다.", "subtitle", ref)
        if c["start_ms"] < prev_end:
            return CheckResult("C07", FAIL, f"자막 {i} 과 {i + 1}의 시간이 겹칩니다.", "subtitle", ref)
        prev_end = c["end_ms"]
    if prev_end != duration_sec * 1000:
        return CheckResult("C07", FAIL, f"자막 합계 {prev_end / 1000:.1f}초가 장면 시간 {duration_sec}초와 다릅니다.",
                           "subtitle", ref)
    return CheckResult("C07", PASS, "자막 시간이 장면 시간과 맞습니다.", "subtitle", ref)


# ---------- C10 경고 문장 반영 ----------
_SENT_BREAK = re.compile(r"(?<=[.!?。])\s+|\n+")
# 단어 끝의 조사를 떼어 내 비교한다. "장갑은"과 "장갑을"을 같은 단어로 보기 위해서다. 긴 조사부터 확인한다.
_PARTICLES = ("으로", "에서", "까지", "부터", "하고", "이나", "에게", "을", "를", "이", "가", "은", "는", "에", "의",
              "와", "과", "로", "도", "만")


def content_tokens(text: str, stop: set[str]) -> set[str]:
    """비교에 쓸 내용어 집합. 두 글자 이상 단어에서 조사를 떼고, 경고 표현 자체("반드시", "주의")는 뺀다.
    경고 표현은 거의 모든 주의사항에 들어 있어, 넣으면 서로 다른 경고끼리도 같다고 판단하기 때문이다."""
    out = set()
    for w in re.findall(r"[가-힣A-Za-z0-9]{2,}", text):
        for p in _PARTICLES:
            if w.endswith(p) and len(w) - len(p) >= 2:
                w = w[: -len(p)]
                break
        if w not in stop:
            out.add(w)
    return out


def warning_sentences(paragraphs: list[dict], terms: list[str]) -> list[dict]:
    """원고에서 경고·금지 표현이 들어 있는 문장을 찾는다. [{"paragraph": "p3", "sentence": "..."}]"""
    out = []
    low_terms = [t.lower() for t in terms]
    for p in paragraphs:
        for s in _SENT_BREAK.split(p["text"]):
            s = s.strip().lstrip("- ").strip()
            if len(s) >= 5 and any(t in s.lower() for t in low_terms):
                out.append({"paragraph": p["id"], "sentence": s})
    return out


def reflected(sentence: str, targets: list[str], stop: set[str]) -> bool:
    """경고 문장이 대상 글(주의사항 등) 가운데 하나에 반영되었는지 내용어 겹침으로 판단한다.
    기준: 문장 내용어의 40% 이상(최소 2개)이 한 대상 글에 들어 있으면 반영된 것으로 본다. 내용어가 하나뿐이면 그 하나가 있으면 된다.
    40%는 같은 경고를 다른 말로 옮긴 경우("헐렁한 장갑 금지"와 "헐렁한 장갑은 쓰지 않는다")를 잡으면서,
    단어 하나만 우연히 겹친 경우는 걸러 내도록 샘플 문장으로 정한 값이다."""
    s_tok = content_tokens(sentence, stop)
    if not s_tok:
        return True
    need = 1 if len(s_tok) == 1 else max(2, -(-len(s_tok) * 4 // 10))
    return any(len(s_tok & content_tokens(t, stop)) >= need for t in targets)


def check_warnings(paragraphs: list[dict], targets: list[str], terms: list[str]) -> CheckResult:
    """C10: 원고의 경고·금지 문장이 주의사항에 반영되었는지. 빠진 문장 목록을 data["missing"]에 담아 돌려준다.
    결과를 받은 쪽(review.py)이 빠진 문장을 주의사항 후보(source='rule')로 더하고 경고로 표시한다."""
    stop = {t for term in terms for t in re.findall(r"[가-힣A-Za-z0-9]{2,}", term)}
    found = warning_sentences(paragraphs, terms)
    missing = [w for w in found if not reflected(w["sentence"], targets, stop)]
    if missing:
        return CheckResult("C10", WARN, f"원고의 경고 문장 {len(missing)}개가 주의사항에 없습니다.", "run",
                           data={"missing": missing})
    return CheckResult("C10", PASS, f"원고의 경고 문장 {len(found)}개가 모두 반영되었습니다.", "run")


# ---------- C12 과장·단정 표현 ----------
def check_hype(text: str, terms: list[str], source_text: str, target_type: str, ref=None) -> CheckResult:
    """C12: 과장·단정 표현 사전의 표현이 없는지. 원고에 이미 있는 표현은 원고를 옮긴 것이므로 문제 삼지 않는다. 경고만 한다."""
    src = source_text.lower()
    hits = [t for t in terms if t.lower() in (text or "").lower() and t.lower() not in src]
    if hits:
        return CheckResult("C12", WARN, f"과장·단정 표현: {', '.join(hits)}", target_type, ref, {"hits": hits})
    return CheckResult("C12", PASS, "과장·단정 표현이 없습니다.", target_type, ref)


# ---------- 실행 하나 전체 검수 ----------
@dataclass
class CheckInput:
    """실행 하나의 결과를 검수에 필요한 모양으로 모은 것. review.build_input()이 DB에서 만든다.
    scenes: [{"id","seq","title","key_point","source_paragraphs","screen_description","visual_suggestion",
              "on_screen_text","duration_sec","char_budget","narration": {"id","body"} 또는 None,"cues":[...]}]
    manual: {"id","title","intro","steps":[{"id","seq","title","instruction","tip","source_paragraphs"}],
             "cautions":[{"body"}],"schedule":[{"step_seq","title","start_offset_day","duration_days"}]} 또는 None"""
    content_type: str
    language: str
    keywords: list[str]
    subtitle_max_chars: int
    paragraphs: list[dict]
    expected_scene_count: Optional[int] = None
    outline: Optional[dict] = None
    scenes: list[dict] = field(default_factory=list)
    manual: Optional[dict] = None


def run_checks(inp: CheckInput) -> list[CheckResult]:
    """C02~C12를 모두 돌린다(C01은 생성 단계의 스키마 검증 결과라 여기서 다시 하지 않는다).
    결과는 대상마다 하나씩 나오며, 모두 원래 결과(pass, warn, fail) 그대로다. 저장 정책(fail을 warn으로)은 review.py가 정한다."""
    out: list[CheckResult] = []
    para_ids = {p["id"] for p in inp.paragraphs}
    by_id = {p["id"]: p for p in inp.paragraphs}
    full_source = "\n".join(p["text"] for p in inp.paragraphs)
    hype = load_terms("hype_terms.txt")
    texts: list[str] = []                      # C05 키워드 검색 대상(결과 전체)

    if inp.outline is not None:
        o = inp.outline
        o_text = " ".join([o["title"], o["summary"], *o.get("learning_objectives", [])])
        texts.append(o_text)
        if inp.expected_scene_count is not None:
            out.append(check_scene_count(len(inp.scenes), inp.expected_scene_count))
        out.append(check_language(o_text + " " + " ".join(s["title"] + " " + s["key_point"] for s in inp.scenes),
                                  inp.language, "outline"))
        out.extend(check_sources([{"id": s["id"], "seq": s["seq"], "source_paragraphs": s["source_paragraphs"]}
                                  for s in inp.scenes], para_ids, "scene"))
        for s in inp.scenes:
            detail = " ".join(x for x in (s.get("screen_description"), s.get("visual_suggestion"),
                                          s.get("on_screen_text")) if x)
            scene_text = " ".join([s["title"], s["key_point"], detail])
            texts.append(scene_text)
            if detail:
                out.append(check_language(detail, inp.language, "scene", s["id"]))
            out.append(check_hype(scene_text, hype, full_source, "scene", s["id"]))
            narr = s.get("narration")
            if narr:
                texts.append(narr["body"])
                out.append(check_budget(narr["body"], s["char_budget"], "narration", narr["id"]))
                out.append(check_language(narr["body"], inp.language, "narration", narr["id"]))
                out.append(check_hype(narr["body"], hype, full_source, "narration", narr["id"]))
                out.append(check_subtitle_lines(s.get("cues") or [], inp.subtitle_max_chars, narr["id"]))
                out.append(check_subtitle_timing(s.get("cues") or [], s["duration_sec"], narr["id"]))

    caution_targets: list[str] = []
    if inp.manual is not None:
        mm = inp.manual
        for st in mm["steps"]:
            st_text = " ".join(x for x in (st["title"], st["instruction"], st.get("tip")) if x)
            texts.append(st_text)
            ev = "\n".join(by_id[i]["text"] for i in st["source_paragraphs"] if i in by_id) or full_source
            out.append(check_numbers(st_text, ev, "manual_step", st["id"], label=f"단계 {st['seq']}: "))
            out.append(check_hype(st_text, hype, full_source, "manual_step", st["id"]))
        out.extend(check_sources([{"id": st["id"], "seq": st["seq"], "source_paragraphs": st["source_paragraphs"]}
                                  for st in mm["steps"]], para_ids, "manual_step"))
        caution_text = "\n".join(c["body"] for c in mm["cautions"])
        texts.append(caution_text)
        if caution_text:
            out.append(check_numbers(caution_text, full_source, "manual", mm["id"], label="주의사항: "))
        out.append(check_schedule(sorted(mm["schedule"], key=lambda x: x["step_seq"] if x.get("step_seq") is not None
                                         else x.get("seq", 0))))
        out[-1].target_ref = mm["id"]
        out.append(check_language(" ".join([mm["title"], mm.get("intro") or "", *(s["instruction"] for s in mm["steps"])]),
                                  inp.language, "manual", mm["id"]))
        caution_targets = [c["body"] for c in mm["cautions"]]
    else:
        # 영상형만 만들었으면 주의사항 대신 장면의 내레이션, 화면 글, 장면 주의사항을 대상으로 본다.
        for s in inp.scenes:
            caution_targets += [x for x in (s.get("screen_description"), s.get("on_screen_text"),
                                            (s.get("narration") or {}).get("body")) if x]
            caution_targets += [c for c in s.get("cautions", [])]

    out.append(check_warnings(inp.paragraphs, caution_targets, load_terms("warning_terms.txt")))
    out.append(check_keywords(inp.keywords, "\n".join(texts)))
    return out
