# schemas.py : LLM 단계별 출력 JSON 스키마(설계서 9절).
# 이 모델의 model_json_schema()가 Ollama의 format 인자로 들어가 모델이 이 형식대로만 답하게 하고,
# 받은 답은 같은 모델로 다시 검증한다(llm_client.generate, 검수 C01).
#
# 스키마를 정할 때의 원칙
# 1. 숫자 규칙(글자 수, 장면 수, 길이 범위)은 스키마에 넣지 않는다. 스키마 검증에 실패하면 단계 전체를
#    다시 요청해야 하지만, 숫자 규칙은 코드 검수(C02, C04 등)가 어느 장면이 틀렸는지까지 알려 주므로
#    그쪽에서 확인하는 편이 재요청 범위가 좁다.
# 2. Field의 description은 JSON 스키마에 들어가 모델에게 필드의 뜻을 알려 주는 짧은 지시문 역할을 한다.
# 3. 필드 이름은 DB 컬럼 이름과 맞춰 저장할 때 바꿔 적는 실수를 줄인다.
from typing import Literal, Optional

from pydantic import BaseModel, Field


# ---------- 3단계 구조화·구성안 (outline_v1) ----------
class OutlineScene(BaseModel):
    seq: int = Field(description="장면 순서. 1부터 시작한다.")
    title: str = Field(description="장면 제목. 짧은 명사구로 쓴다.")
    key_point: str = Field(description="이 장면의 학습 포인트 하나를 한 문장으로 쓴다.")
    source_paragraphs: list[str] = Field(description="근거가 된 원고 문단 번호 목록. 예: [\"p3\", \"p4\"]")


class OutlineOut(BaseModel):
    title: str = Field(description="콘텐츠 제목")
    summary: str = Field(description="핵심 요약. 두세 문장.")
    learning_objectives: list[str] = Field(description="학습목표. '~할 수 있다' 형태로 쓴다.")
    scenes: list[OutlineScene]


# ---------- 4단계 장면·단계 상세 (scene_detail_v1) ----------
class SceneDetailOut(BaseModel):
    screen_description: str = Field(description="화면에 무엇이 어떻게 보이는지. 촬영이나 제작이 가능한 수준으로 구체적으로 쓴다.")
    visual_suggestion: str = Field(description="시각자료 제안. 도식, 자막 강조, 클로즈업, 표 등.")
    on_screen_text: str = Field(description="화면에 띄울 짧은 문구. 30자 안팎.")


# ---------- 5a단계 내레이션 (narration_v1) ----------
class NarrationOut(BaseModel):
    narration: str = Field(description="장면 내레이션 원고. 소리 내어 읽을 문장만 쓴다.")


# ---------- 5b단계 맞춤 매뉴얼 (manual_v1) ----------
class ManualStepOut(BaseModel):
    seq: int = Field(description="단계 순서. 1부터 시작한다.")
    title: str = Field(description="단계 제목")
    instruction: str = Field(description="대상과 난이도에 맞춘 작업 지시")
    tip: Optional[str] = Field(default=None, description="도움말. 없으면 null.")
    source_paragraphs: list[str] = Field(description="근거 문단 번호 목록")
    # 소요 기간과 반복 주기는 일정 배치에 쓴다. 날짜 계산은 코드가 하고(schedule.py), LLM은 원고에서 기간만 뽑는다.
    duration_days: int = Field(default=1, description="이 단계에 걸리는 날 수. 원고에 없으면 1.")
    interval_days: Optional[int] = Field(default=None, description="반복 작업이면 반복 주기(일). 한 번만 하면 null.")


class CautionOut(BaseModel):
    severity: Literal["info", "warning", "danger"] = Field(description="info는 참고, warning은 주의, danger는 위험")
    body: str = Field(description="주의사항 문장")


class ManualOut(BaseModel):
    title: str = Field(description="매뉴얼 제목")
    intro: str = Field(description="매뉴얼 소개. 누구를 위해 무엇을 하는 매뉴얼인지 두세 문장.")
    steps: list[ManualStepOut]
    cautions: list[CautionOut]


# ---------- 긴 원고 요약 (설계서 12절의 잘림 대비) ----------
class ChunkPoint(BaseModel):
    source_paragraphs: list[str] = Field(description="이 요점의 근거 문단 번호 목록")
    summary: str = Field(description="요점 한두 문장. 수치와 고유명사는 원고 그대로 쓴다.")


class ChunkSummaryOut(BaseModel):
    points: list[ChunkPoint]


# 단계 이름과 출력 모델의 대응. seed_prompts.py와 PUT /api/prompts/{stage}가 출력 스키마를 여기서 만든다.
# quiz는 선택 기능이라 아직 모델이 없다(설계서 11절 9번).
STAGE_MODELS: dict[str, type[BaseModel]] = {
    "outline": OutlineOut,
    "scene_detail": SceneDetailOut,
    "narration": NarrationOut,
    "manual": ManualOut,
}
