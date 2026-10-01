# fake_llm.py : 테스트용 가짜 Ollama. 실제 모델을 부르지 않는다(CLAUDE.md 작업 규칙).
# llm_client.client.chat 자리에 monkeypatch로 넣으면, format으로 넘어온 스키마 이름(title)을 보고
# 그 단계에 맞는 그럴듯한 JSON을 돌려준다. 프롬프트에서 장면 수, 글자 수 예산, 문단 번호를 읽어
# 규칙을 지키는 답을 만들기 때문에, 기본 상태에서는 모든 검수를 통과한다.
# overrides에 단계 이름별 함수를 넣으면 특정 단계의 답을 바꿔 실패 경로를 시험할 수 있다.
import json
import re
from types import SimpleNamespace

SENTENCE = "드릴을 켜기 전에 배터리가 끝까지 끼워졌는지 확인합니다. "


def _user(kw) -> str:
    return next(m["content"] for m in kw["messages"] if isinstance(m, dict) and m.get("role") == "user")


def _system(kw) -> str:
    return next(m["content"] for m in kw["messages"] if isinstance(m, dict) and m.get("role") == "system")


def paragraph_ids(text: str) -> list[str]:
    """<source> 안의 [p3] 또는 [p3 · 표], 요약본의 [p3, p4] 모양에서 문단 번호를 뽑는다."""
    return list(dict.fromkeys(re.findall(r"\b(p\d+)\b", text)))


def narration_text(budget: int) -> str:
    """공백을 뺀 글자 수가 budget에 맞는 내레이션. 문장을 되풀이한 뒤 공백 제외 글자 수로 자른다."""
    out, count = "", 0
    while count < budget:
        for ch in SENTENCE:
            if count >= budget:
                break
            out += ch
            if not ch.isspace():
                count += 1
    return out.strip()


def default_answer(title: str, kw) -> dict:
    system, user = _system(kw), _user(kw)
    if title == "OutlineOut":
        n = int(re.search(r"정확히 (\d+)개", system).group(1))
        ids = paragraph_ids(user) or ["p1"]
        return {"title": "전동드릴 안전 사용법", "summary": "작업 전 점검부터 보관까지 익힌다.",
                "learning_objectives": ["작업 전 점검 항목을 말할 수 있다"],
                "scenes": [{"seq": i, "title": f"장면{i} 보호장갑", "key_point": f"학습 포인트 {i} 보호장갑",
                            "source_paragraphs": [ids[(i - 1) % len(ids)]]} for i in range(1, n + 1)]}
    if title == "SceneDetailOut":
        return {"screen_description": "작업자가 드릴 배터리를 끼우는 손을 가까이 보여 준다.",
                "visual_suggestion": "배터리 체결 부위 클로즈업", "on_screen_text": "배터리 체결 확인"}
    if title == "NarrationOut":
        budget = int(re.search(r"공백을 빼고 (\d+)자", system).group(1))
        return {"narration": narration_text(budget)}
    if title == "ManualOut":
        ids = paragraph_ids(user) or ["p1"]
        return {"title": "전동드릴 작업 매뉴얼", "intro": "신입 사원을 위한 매뉴얼이다.",
                "steps": [{"seq": 1, "title": "배터리 점검", "instruction": "배터리를 끝까지 끼운다.", "tip": None,
                           "source_paragraphs": [ids[0]], "duration_days": 1, "interval_days": None},
                          {"seq": 2, "title": "보호구 착용", "instruction": "보안경과 장갑을 착용한다.",
                           "tip": "손에 맞는 장갑을 고른다.", "source_paragraphs": [ids[-1]],
                           "duration_days": 2, "interval_days": 7}],
                "cautions": [{"severity": "danger", "body": "헐렁한 장갑은 회전부에 말려 들어갈 수 있다."}]}
    if title == "ChunkSummaryOut":
        ids = paragraph_ids(user) or ["p1"]
        return {"points": [{"source_paragraphs": [i], "summary": f"{i} 요점"} for i in ids]}
    raise AssertionError(f"모르는 스키마: {title}")


class FakeOllama:
    """호출 기록(calls)과 단계별 답 바꾸기(overrides)를 가진 가짜 chat 함수."""

    def __init__(self, overrides=None, prompt_tokens=500):
        self.calls: list[dict] = []
        self.overrides = overrides or {}      # {"OutlineOut": fn(kw, n번째 호출) -> dict 또는 str}
        self.prompt_tokens = prompt_tokens
        self.count: dict[str, int] = {}

    def __call__(self, **kw):
        self.calls.append(kw)
        title = kw["format"]["title"]
        n = self.count[title] = self.count.get(title, 0) + 1
        if title in self.overrides:
            ans = self.overrides[title](kw, n)
        else:
            ans = default_answer(title, kw)
        content = ans if isinstance(ans, str) else json.dumps(ans, ensure_ascii=False)
        return SimpleNamespace(prompt_eval_count=self.prompt_tokens, eval_count=50,
                               message=SimpleNamespace(content=content))

    def titles(self) -> list[str]:
        return [c["format"]["title"] for c in self.calls]
