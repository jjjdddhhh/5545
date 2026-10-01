# schemas.py : API 요청·응답 본문의 Pydantic 모델.
# 설계서 6절: "모든 응답 본문은 Pydantic 모델로 정의하고, OpenAPI 문서(/docs)를 프론트엔드와의 계약서로 쓴다."
# LLM 출력 스키마(llm/schemas.py)와는 일부러 분리했다. LLM 스키마는 프롬프트 버전과 함께 바뀌고,
# API 스키마는 화면과의 약속이라 따로 움직여야 하기 때문이다.
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app import config


class ORM(BaseModel):
    """SQLAlchemy 객체를 그대로 넘겨 응답을 만들 수 있게 하는 공통 부모(from_attributes)."""
    model_config = ConfigDict(from_attributes=True)


# ---------- 프로젝트 ----------
class ProjectIn(BaseModel):
    # 200자는 project.title VARCHAR(200)과 맞춘 값이다. 1자 이상이어야 목록에서 구분할 수 있다.
    title: str = Field(min_length=1, max_length=200)


class ProjectOut(ORM):
    id: int
    title: str
    status: str            # draft, generating, ready, error
    created_at: datetime
    updated_at: datetime


class RunBrief(ORM):
    """목록과 상세 화면에서 보여 줄 실행 요약."""
    id: int
    status: str            # queued, running, done, failed
    current_stage: Optional[str] = None
    llm_model: str
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    error_message: Optional[str] = None


class ProjectListItem(ProjectOut):
    latest_run: Optional[RunBrief] = None   # 목록 화면의 "최근 실행 상태" 표시용(설계서 5절)


# ---------- 원고 ----------
ParagraphKind = Literal["body", "heading", "table"]   # text_cleaner가 만드는 문단 종류 세 가지


class Paragraph(BaseModel):
    id: str                 # p1, p2, ... 근거 추적에 쓰는 번호
    kind: ParagraphKind
    text: str


class ParagraphIn(BaseModel):
    """미리보기에서 사용자가 합치거나 나눈 문단. 번호(id)는 서버가 다시 매기므로 받지 않는다."""
    kind: ParagraphKind = "body"
    text: str = Field(min_length=1)


class ParagraphsIn(BaseModel):
    paragraphs: list[ParagraphIn] = Field(min_length=1)  # 문단이 하나도 없으면 생성할 근거가 없다


class SourceOut(ORM):
    """원고 비교 미리보기. 원문(raw_text)과 정제본(clean_text)을 나란히 보여 주는 데 쓴다."""
    id: int
    project_id: int
    source_type: str        # paste 또는 file
    file_name: Optional[str] = None
    raw_text: str
    clean_text: str
    paragraphs: list[Paragraph]
    char_count: int
    created_at: datetime
    # stats와 warnings는 DB 컬럼이 없어 업로드 응답에서만 정확한 값을 준다.
    # 다시 조회할 때 stats는 문단 목록에서 다시 세고, warnings는 빈 목록이 된다.
    stats: dict = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


# ---------- 생성 조건 ----------
class SettingIn(BaseModel):
    """조건 설정 화면의 입력. 필수 다섯 항목과 고급 설정으로 나뉜다(설계서 5절)."""
    # 필수 항목
    content_type: Literal["video", "manual", "both"]
    audience: str = Field(min_length=1, max_length=100)        # generation_setting.audience VARCHAR(100)
    difficulty: Literal["beginner", "intermediate", "advanced"]
    # 목표 분량과 장면 수 중 하나는 있어야 한다(아래 검사기, schema.sql의 CHECK 제약과 같은 규칙).
    # 하한 10초는 장면 하나를 만들 수 있는 최소 길이로 잡았고, 상한은 config.MAX_DURATION_SEC다.
    target_duration_sec: Optional[int] = Field(default=None, ge=10, le=config.MAX_DURATION_SEC)
    scene_count: Optional[int] = Field(default=None, ge=1, le=config.MAX_SCENES)
    output_language: str = Field(default="ko", min_length=2, max_length=10)  # 언어 코드(ko, en 등)
    # 고급 설정(화면에서는 기본으로 접혀 있다)
    tone: Optional[str] = Field(default=None, max_length=50)   # generation_setting.tone VARCHAR(50)
    keywords: list[str] = Field(default_factory=list, max_length=20)  # 20개를 넘으면 장면보다 키워드가 많아진다
    # 분당 글자 수 100~600: 아주 느린 낭독(분당 100자)부터 빠른 낭독(분당 600자)까지 허용한다.
    narration_cpm: int = Field(default=config.NARRATION_CPM, ge=100, le=600)
    # 장면당 기본 시간 5~300초: 5초보다 짧으면 문장 하나도 못 읽고, 5분을 넘으면 장면 하나에 학습 포인트 하나라는 원칙이 무너진다.
    scene_default_sec: int = Field(default=config.SCENE_DEFAULT_SEC, ge=5, le=300)
    # 자막 한 줄 8~40자: subtitle_cue.body VARCHAR(100)에 두 줄과 줄바꿈이 들어가는 범위다(40*2+1=81).
    subtitle_max_chars: int = Field(default=config.SUBTITLE_MAX_CHARS, ge=8, le=40)

    @model_validator(mode="after")
    def need_duration_or_count(self) -> "SettingIn":
        # schema.sql CHECK (target_duration_sec IS NOT NULL OR scene_count IS NOT NULL)와 같은 규칙을
        # DB에 보내기 전에 검사해, MySQL 오류 대신 알아보기 쉬운 422 메시지를 돌려준다.
        if self.target_duration_sec is None and self.scene_count is None:
            raise ValueError("목표 분량(초)과 장면 수 중 하나는 입력해야 합니다.")
        # 빈 키워드와 앞뒤 공백, 중복을 없앤다. 순서는 사용자가 입력한 순서를 지킨다.
        self.keywords = list(dict.fromkeys(k.strip() for k in self.keywords if k.strip()))
        return self


class SettingOut(ORM):
    id: int
    project_id: int
    content_type: str
    audience: str
    difficulty: str
    target_duration_sec: Optional[int] = None
    scene_count: Optional[int] = None
    output_language: str
    tone: Optional[str] = None
    keywords: Optional[list[str]] = None
    narration_cpm: int
    scene_default_sec: int
    subtitle_max_chars: int
    created_at: datetime


class ProjectDetail(ProjectOut):
    """GET /api/projects/{id}: 프로젝트 정보와 최신 결과 요약(설계서 6절)."""
    source: Optional[dict] = None       # 최근 원고 요약 {id, char_count, paragraph_count, file_name}
    setting: Optional[SettingOut] = None
    latest_run: Optional[RunBrief] = None
    outline: Optional[dict] = None      # 현재 구성안 요약 {id, title, scene_count}
    manual: Optional[dict] = None       # 현재 매뉴얼 요약 {id, title, step_count}


# ---------- 생성 실행 ----------
class RunCreated(BaseModel):
    run_id: int            # POST /runs는 202와 이 값만 바로 돌려주고, 진행은 SSE로 따로 본다(설계서 6절)


# ---------- 구성안과 장면 (GET /api/projects/{id}/outline) ----------
class CueOut(ORM):
    id: int
    seq: int
    start_ms: int          # 장면 시작 기준. SRT로 내보낼 때 앞 장면 시간을 더해 누적한다
    end_ms: int
    body: str              # 줄바꿈("\n") 포함 최대 2줄


class NarrationOut(ORM):
    id: int
    body: str
    char_count: int        # 공백을 뺀 글자 수
    est_duration_sec: float
    is_edited: bool        # 사용자가 고친 내레이션이면 장면 재생성 때 덮어쓰지 않는다


class SceneOut(ORM):
    id: int
    seq: int
    title: str
    key_point: str
    source_paragraphs: list[str]
    screen_description: Optional[str] = None
    visual_suggestion: Optional[str] = None
    on_screen_text: Optional[str] = None
    duration_sec: int
    char_budget: int
    edited_fields: list[str] = Field(default_factory=list)
    start_sec: int = 0                     # 영상 전체에서 이 장면이 시작하는 시각(초). 앞 장면 시간의 합이다
    narration: Optional[NarrationOut] = None
    cues: list[CueOut] = Field(default_factory=list)
    check_status: str = "none"             # 이 장면에 걸린 자동 검수의 가장 나쁜 결과(pass, warn, fail, none). 장면 목록의 점 색


class OutlineInfo(ORM):
    id: int
    run_id: int
    title: str
    summary: str
    learning_objectives: list[str]
    created_at: datetime


class OutlineView(BaseModel):
    outline: OutlineInfo
    scenes: list[SceneOut]
    total_sec: int                         # 장면 시간의 합(영상 전체 길이)


# ---------- 직접 수정 ----------
class NarrationPatch(BaseModel):
    # narration.body는 TEXT(최대 65,535바이트)다. 한글 3바이트 기준 2만 자 안쪽이면 안전하다.
    body: str = Field(min_length=1, max_length=20000)


# ---------- 매뉴얼과 일정 (GET /api/projects/{id}/manual) ----------
class ManualStepOut(ORM):
    id: int
    seq: int
    title: str
    instruction: str
    tip: Optional[str] = None
    source_paragraphs: list[str]
    edited_fields: list[str] = Field(default_factory=list)
    check_status: str = "none"     # 이 단계에 걸린 자동 검수의 가장 나쁜 결과


class CautionOut(ORM):
    id: int
    severity: str                  # info, warning, danger
    body: str
    source: str                    # ai: 모델이 만든 것, rule: 검수 C10이 원고의 경고 문장에서 더한 것, user: 사용자가 더한 것


class ScheduleItemOut(ORM):
    id: int
    seq: int
    manual_step_id: Optional[int] = None
    title: str
    start_offset_day: int          # 시작일 기준 며칠째(0부터)
    duration_days: int
    interval_days: Optional[int] = None
    note: Optional[str] = None
    source: str


class ManualInfo(ORM):
    id: int
    run_id: int
    audience: str
    difficulty: str
    title: str
    intro: Optional[str] = None
    created_at: datetime


class ManualView(BaseModel):
    manual: ManualInfo
    steps: list[ManualStepOut]
    cautions: list[CautionOut]
    schedule: list[ScheduleItemOut]
    total_days: int                # 일정 전체 기간(마지막 항목이 끝나는 날까지)


class ManualStepPatch(BaseModel):
    """매뉴얼 단계에서 사용자가 고칠 수 있는 필드. 보낸 필드만 바꾼다."""
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    instruction: Optional[str] = Field(default=None, min_length=1)
    tip: Optional[str] = None


class ScheduleItemPatch(BaseModel):
    """일정 항목에서 사용자가 고칠 수 있는 필드. 시작일(며칠째)은 받지 않는다. 기간이 바뀌면 코드가 다시 배치하기 때문이다."""
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    duration_days: Optional[int] = Field(default=None, ge=1, le=365)
    interval_days: Optional[int] = Field(default=None, ge=0, le=365)   # 0을 보내면 반복 없음으로 바꾼다
    note: Optional[str] = Field(default=None, max_length=500)


# ---------- 장면 수정·재생성·순서 ----------
class ScenePatch(BaseModel):
    """장면에서 사용자가 직접 고칠 수 있는 필드(설계서 6절 PATCH /api/scenes). 보낸 필드만 바꾼다."""
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    key_point: Optional[str] = Field(default=None, min_length=1, max_length=500)
    screen_description: Optional[str] = None
    visual_suggestion: Optional[str] = None
    on_screen_text: Optional[str] = Field(default=None, max_length=300)


class RegenerateIn(BaseModel):
    """다시 만들 부분. detail은 화면 설명·시각자료·화면 텍스트, narration은 내레이션과 자막이다."""
    parts: list[Literal["detail", "narration"]] = Field(default_factory=lambda: ["detail", "narration"], min_length=1)


class RegenerateOut(BaseModel):
    scene: SceneOut
    regenerated: list[str]         # 실제로 다시 만든 부분
    kept: list[str]                # 사용자가 고쳐서 그대로 둔 필드(설계서 10절 규칙 2)


class SceneOrderIn(BaseModel):
    scene_ids: list[int] = Field(min_length=1)   # 현재 구성안의 장면 id를 원하는 순서대로 모두 보낸다


class SceneCreate(BaseModel):
    """결과 작업공간의 "+ 장면 추가". 새 장면은 맨 뒤에 붙고, 시간은 장면당 기본 시간이다."""
    title: str = Field(min_length=1, max_length=200)
    key_point: str = Field(default="", max_length=500)
    source_paragraphs: list[str] = Field(default_factory=list)


# ---------- 검수 ----------
class CheckItem(ORM):
    id: int
    check_code: str
    label: str = ""                # 화면에 보여 줄 항목 이름(review.CHECK_LABEL)
    target_type: Optional[str] = None
    target_id: Optional[int] = None
    result: str                    # pass, warn, fail, unchecked
    message: Optional[str] = None
    checked_by: Optional[int] = None
    checked_at: Optional[datetime] = None


class ChecksView(BaseModel):
    run_id: int
    summary: dict                  # {pass, warn, fail, total, pass_rate} 자동 항목만 센다
    auto: list[CheckItem]          # C01~C12
    human: list[CheckItem]         # H01~H03


class HumanCheckIn(BaseModel):
    checked: bool
    note: Optional[str] = Field(default=None, max_length=500)


# ---------- 프롬프트 템플릿 ----------
class PromptVersion(BaseModel):
    id: Optional[int] = None       # 파일 원문(DB에 아직 없음)이면 None
    version: int
    is_active: bool
    created_at: Optional[datetime] = None


class PromptView(BaseModel):
    stage: str
    source: str                    # db: prompt_template의 활성 버전, file: llm/prompts/의 원문(DB에 아직 없음)
    version: int
    system_prompt: str
    user_template: str
    output_schema: dict
    placeholders: list[str]        # 템플릿 속 {이름} 목록
    versions: list[PromptVersion]


class PromptIn(BaseModel):
    system_prompt: str = Field(min_length=1)
    user_template: str = Field(min_length=1)


class PromptSaved(PromptView):
    warnings: list[str] = Field(default_factory=list)   # 버전 1에 있던 변수가 빠졌으면 알려 준다
