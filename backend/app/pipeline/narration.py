# narration.py : 5a단계 내레이션(설계서 4절). LLM이 장면별 내레이션을 쓰고, 자막은 코드(subtitles.py)가 나눈다.
# 글자 수 예산은 2단계(budget)가 정한 값이다. 생성 직후 C04(예산 ±15%)와 C11(출력 언어)을 확인해,
# 실패하면 그 장면의 내레이션만 1회 다시 요청한다(설계서 10절 C04 "그 장면의 내레이션만 다시 요청한다").
import re
from dataclasses import dataclass, field
from typing import Optional

from app import config
from app.llm.prompt_store import PromptSet, common_values
from app.llm.schemas import NarrationOut
from app.pipeline import checks
from app.pipeline.llm_step import StepRecorder, call_llm
from app.pipeline.scene_detail import source_text_for


@dataclass
class NarrationInput:
    seq: int
    title: str
    key_point: str
    screen_description: Optional[str]
    on_screen_text: Optional[str]
    duration_sec: int
    char_budget: int
    source_paragraphs: list[str]


@dataclass
class NarrationResult:
    text: str
    retried: bool = False
    failures: list[checks.CheckResult] = field(default_factory=list)


def clean_narration(text: str) -> str:
    """모델이 내레이션에 붙이기 쉬운 군더더기를 지운다.
    - "(화면: ...)" 같은 괄호 지시문은 소리 내어 읽지 않으므로 지운다(프롬프트 규칙 2를 코드로 한 번 더 지킨다).
    - 앞뒤 따옴표와 "내레이션:" 같은 머리말을 지운다.
    - 여러 줄로 나뉜 답은 한 문단으로 잇는다(자막 분할은 subtitles.py가 따로 한다)."""
    text = re.sub(r"\((?:화면|자막|효과음|음악|BGM)[^)]*\)", "", text or "")
    text = re.sub(r"^\s*(내레이션|나레이션|Narration)\s*[:：]\s*", "", text.strip(), flags=re.IGNORECASE)
    text = text.strip().strip("\"'“”‘’")
    return re.sub(r"\s+", " ", text).strip()


# C04 글자 수 검사는 검수 전체(checks.run_checks)와 함께 쓰려고 checks.check_budget에 둔다.
check_budget = checks.check_budget


def generate_narration(recorder: StepRecorder, prompt: PromptSet, setting, scene: NarrationInput,
                       paragraphs_by_id: dict[str, dict], ref: Optional[int] = None) -> NarrationResult:
    """장면 하나의 내레이션을 쓴다. ref는 검수 결과에 남길 대상(생성 중에는 장면 id)."""
    tol = config.NARRATION_TOLERANCE
    values = {**common_values(setting), "seq": scene.seq, "scene_title": scene.title, "key_point": scene.key_point,
              "screen_description": scene.screen_description or "(없음)",
              "on_screen_text": scene.on_screen_text or "(없음)",
              "duration_sec": scene.duration_sec, "char_budget": scene.char_budget,
              # 프롬프트에 허용 범위를 숫자로 적어 준다. 작은 모델은 "±15%"보다 "128자에서 172자"를 더 잘 지킨다.
              "char_min": int(scene.char_budget * (1 - tol) + 0.999), "char_max": int(scene.char_budget * (1 + tol)),
              "source_text": source_text_for(paragraphs_by_id, scene.source_paragraphs)}
    target = {"scene_seq": scene.seq, "scene_ref": ref, "char_budget": scene.char_budget}

    out = call_llm(recorder, "narration", prompt, values, NarrationOut, target=target)
    text = clean_narration(out.narration)
    failures = _validate(text, scene.char_budget, setting.output_language, ref)
    retried = False
    if failures:
        retried = True
        out = call_llm(recorder, "narration", prompt, values, NarrationOut,
                       feedback=checks.feedback_text(failures), target={**target, "retry": True})
        text = clean_narration(out.narration)
        failures = _validate(text, scene.char_budget, setting.output_language, ref)
    return NarrationResult(text=text, retried=retried, failures=failures)


def _validate(text: str, budget: int, language: str, ref) -> list[checks.CheckResult]:
    results = [check_budget(text, budget, "narration", ref), checks.check_language(text, language, "narration", ref)]
    return [r for r in results if r.failed]
