# scene_detail.py : 4단계 장면·단계 상세(설계서 4절).
# 장면마다 LLM을 따로 부른다. 속도 때문이 아니라(GPU 하나라 어차피 순서대로 돈다) 한 장면만 다시 만들 수 있게 하기 위해서다
# (설계서 12절). 장면 재생성 API(POST /api/scenes/{id}/regenerate)도 이 함수를 그대로 쓴다.
from dataclasses import dataclass, field
from typing import Optional

from app.llm.prompt_store import PromptSet, common_values
from app.llm.schemas import SceneDetailOut
from app.pipeline import checks
from app.pipeline.llm_step import StepRecorder, call_llm
from app.pipeline.text_cleaner import to_prompt

# 장면 상세에서 LLM이 쓰는 필드. 사용자가 이 중 하나를 고쳤으면(edited_fields) 프롬프트에 고정값으로 넘기고
# 결과에서도 덮어쓰지 않는다(설계서 10절 규칙 2). title과 key_point는 구성안 단계가 쓰므로 여기에 없다.
DETAIL_FIELDS = ("screen_description", "visual_suggestion", "on_screen_text")
FIELD_LABEL = {"screen_description": "화면 설명", "visual_suggestion": "시각자료 제안", "on_screen_text": "화면 텍스트",
               "title": "제목", "key_point": "학습 포인트"}
# on_screen_text는 DB에서 VARCHAR(300)이다. 모델이 길게 쓰면 저장할 때 오류가 나므로 자른다.
ON_SCREEN_TEXT_MAX = 300


@dataclass
class SceneInput:
    seq: int
    title: str
    key_point: str
    duration_sec: int
    source_paragraphs: list[str]
    fixed: dict = field(default_factory=dict)   # 사용자가 고친 필드 {필드 이름: 값}. 재생성 때만 채워진다


@dataclass
class SceneDetailResult:
    detail: SceneDetailOut
    retried: bool = False
    failures: list[checks.CheckResult] = field(default_factory=list)


def source_text_for(paragraphs_by_id: dict[str, dict], ids: list[str]) -> str:
    """장면의 근거 문단만 골라 <source> 태그로 감싼다. 근거가 없으면 그 사실을 알려 모델이 지어내지 않게 한다."""
    chosen = [paragraphs_by_id[i] for i in ids if i in paragraphs_by_id]
    if not chosen:
        return "<source>\n(근거 문단이 없습니다. 학습 포인트 문장 안의 내용만 사용한다.)\n</source>"
    return to_prompt(chosen)


def fixed_text(fixed: dict) -> str:
    """고정 필드를 프롬프트에 넣을 문장으로 만든다. 없으면 "없음"."""
    if not fixed:
        return "없음"
    return "; ".join(f"{FIELD_LABEL.get(k, k)}({k}) = {v}" for k, v in fixed.items())


def generate_scene_detail(recorder: StepRecorder, prompt: PromptSet, setting, outline_title: str,
                          scene: SceneInput, paragraphs_by_id: dict[str, dict],
                          scene_ref: Optional[int] = None) -> SceneDetailResult:
    """장면 하나의 화면 설명, 시각자료 제안, 화면 텍스트를 만든다.
    scene_ref는 로그와 검수 결과에 남길 대상 식별값(생성 중에는 seq, 재생성 때는 scene.id)이다."""
    values = {**common_values(setting), "outline_title": outline_title, "seq": scene.seq,
              "scene_title": scene.title, "key_point": scene.key_point, "duration_sec": scene.duration_sec,
              "fixed_fields": fixed_text(scene.fixed),
              "source_text": source_text_for(paragraphs_by_id, scene.source_paragraphs)}
    ref = scene_ref if scene_ref is not None else scene.seq
    target = {"scene_seq": scene.seq, "scene_ref": ref}

    out = call_llm(recorder, "scene_detail", prompt, values, SceneDetailOut, target=target)
    failures = _validate(out, setting.output_language, ref)
    retried = False
    if failures:
        # C11(출력 언어)이 실패하면 이 장면만 1회 다시 요청한다(설계서 10절).
        retried = True
        out = call_llm(recorder, "scene_detail", prompt, values, SceneDetailOut,
                       feedback=checks.feedback_text(failures), target={**target, "retry": True})
        failures = _validate(out, setting.output_language, ref)
    return SceneDetailResult(detail=apply_fixed(out, scene.fixed), retried=retried, failures=failures)


def apply_fixed(out: SceneDetailOut, fixed: dict) -> SceneDetailOut:
    """사용자가 고친 필드는 모델이 무엇을 돌려줬든 원래 값으로 되돌린다(설계서 10절 규칙 2, 결과에서도 덮어쓰지 않는다).
    프롬프트로 "바꾸지 말라"고 했어도 작은 모델은 바꿀 수 있으므로 코드로 한 번 더 지킨다."""
    for k in DETAIL_FIELDS:
        if k in fixed:
            setattr(out, k, fixed[k] or "")
    out.on_screen_text = (out.on_screen_text or "")[:ON_SCREEN_TEXT_MAX]
    return out


def _validate(out: SceneDetailOut, language: str, ref) -> list[checks.CheckResult]:
    text = " ".join([out.screen_description, out.visual_suggestion, out.on_screen_text])
    r = checks.check_language(text, language, "scene", ref)
    return [r] if r.failed else []
