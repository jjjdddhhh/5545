# models.py : db/schema.sql의 테이블 21개를 SQLAlchemy 2 모델로 옮긴 것이다.
# schema.sql이 기준이다. 컬럼 이름, 형식, NULL 허용 여부를 1:1로 맞추고, tests/test_models_schema.py가
# 실제 MySQL에 schema.sql을 적용한 뒤 이 모델과 컬럼 구성을 대조한다. 테이블은 schema.sql로 만들고
# 이 모델로 만들지 않는다(create_all을 쓰지 않는다).
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import (JSON, BigInteger, Boolean, DateTime, Enum, ForeignKey, Integer,
                        Numeric, String, Text, text)
from sqlalchemy.dialects.mysql import MEDIUMTEXT, TINYINT
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

NOW = text("CURRENT_TIMESTAMP")
NOW_ON_UPDATE = text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP")

DIFFICULTY = ("beginner", "intermediate", "advanced")


class Base(DeclarativeBase):
    # MySQL은 INSERT 결과로 기본값을 돌려주지 않으므로, created_at 같은 서버 기본값을 INSERT 직후 다시 읽어 온다.
    __mapper_args__ = {"eager_defaults": True}


def _enum(*values: str, name: str) -> Enum:
    return Enum(*values, name=name, native_enum=True, validate_strings=True)


# ---------- 입력과 설정 ----------
class AppUser(Base):
    __tablename__ = "app_user"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    email: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=NOW)


class Project(Base):
    __tablename__ = "project"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("app_user.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(_enum("draft", "generating", "ready", "error", name="project_status"),
                                        nullable=False, server_default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=NOW)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=NOW_ON_UPDATE)


class SourceDocument(Base):
    __tablename__ = "source_document"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("project.id", ondelete="CASCADE"), nullable=False)
    source_type: Mapped[str] = mapped_column(_enum("paste", "file", name="source_type"), nullable=False)
    file_name: Mapped[Optional[str]] = mapped_column(String(255))
    raw_text: Mapped[str] = mapped_column(MEDIUMTEXT, nullable=False)
    clean_text: Mapped[str] = mapped_column(MEDIUMTEXT, nullable=False)
    paragraphs: Mapped[list[dict]] = mapped_column(JSON, nullable=False)  # [{"id":"p1","kind":"body","text":"..."}]
    char_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=NOW)


class GenerationSetting(Base):
    __tablename__ = "generation_setting"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("project.id", ondelete="CASCADE"), nullable=False)
    content_type: Mapped[str] = mapped_column(_enum("video", "manual", "both", name="content_type"), nullable=False)
    audience: Mapped[str] = mapped_column(String(100), nullable=False)
    difficulty: Mapped[str] = mapped_column(_enum(*DIFFICULTY, name="difficulty"), nullable=False)
    target_duration_sec: Mapped[Optional[int]] = mapped_column(Integer)
    scene_count: Mapped[Optional[int]] = mapped_column(Integer)
    output_language: Mapped[str] = mapped_column(String(10), nullable=False, server_default="ko")
    tone: Mapped[Optional[str]] = mapped_column(String(50))
    keywords: Mapped[Optional[list[str]]] = mapped_column(JSON)
    narration_cpm: Mapped[int] = mapped_column(Integer, nullable=False, server_default="300")
    scene_default_sec: Mapped[int] = mapped_column(Integer, nullable=False, server_default="30")
    subtitle_max_chars: Mapped[int] = mapped_column(Integer, nullable=False, server_default="16")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=NOW)


# ---------- 실행과 이력 ----------
class PromptTemplate(Base):
    __tablename__ = "prompt_template"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    stage: Mapped[str] = mapped_column(
        _enum("outline", "scene_detail", "narration", "manual", "quiz", name="prompt_stage"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    user_template: Mapped[str] = mapped_column(Text, nullable=False)
    output_schema: Mapped[dict] = mapped_column(JSON, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("FALSE"))
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=NOW)


class GenerationRun(Base):
    __tablename__ = "generation_run"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("project.id", ondelete="CASCADE"), nullable=False)
    setting_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("generation_setting.id"), nullable=False)
    source_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("source_document.id"), nullable=False)
    status: Mapped[str] = mapped_column(_enum("queued", "running", "done", "failed", name="run_status"),
                                        nullable=False, server_default="queued")
    current_stage: Mapped[Optional[str]] = mapped_column(String(30))
    llm_model: Mapped[str] = mapped_column(String(80), nullable=False)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    error_message: Mapped[Optional[str]] = mapped_column(Text)


class AgentStepLog(Base):
    __tablename__ = "agent_step_log"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("generation_run.id", ondelete="CASCADE"), nullable=False)
    stage: Mapped[str] = mapped_column(String(30), nullable=False)
    prompt_template_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("prompt_template.id"))
    attempt: Mapped[int] = mapped_column(TINYINT, nullable=False, server_default="1")
    input_json: Mapped[Optional[Any]] = mapped_column(JSON)
    output_json: Mapped[Optional[Any]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(_enum("ok", "retry", "failed", name="step_status"), nullable=False)
    tokens_in: Mapped[Optional[int]] = mapped_column(Integer)
    tokens_out: Mapped[Optional[int]] = mapped_column(Integer)
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=NOW)


# ---------- 영상형 결과 ----------
class Outline(Base):
    __tablename__ = "outline"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("generation_run.id", ondelete="CASCADE"), nullable=False)
    project_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("project.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    learning_objectives: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("TRUE"))
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=NOW)

    scenes: Mapped[list["Scene"]] = relationship(order_by="Scene.seq", back_populates="outline")


class Scene(Base):
    __tablename__ = "scene"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    outline_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("outline.id", ondelete="CASCADE"), nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    key_point: Mapped[str] = mapped_column(String(500), nullable=False)
    source_paragraphs: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    screen_description: Mapped[Optional[str]] = mapped_column(Text)
    visual_suggestion: Mapped[Optional[str]] = mapped_column(Text)
    on_screen_text: Mapped[Optional[str]] = mapped_column(String(300))
    duration_sec: Mapped[int] = mapped_column(Integer, nullable=False)
    char_budget: Mapped[int] = mapped_column(Integer, nullable=False)
    edited_fields: Mapped[Optional[list[str]]] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=NOW_ON_UPDATE)

    outline: Mapped[Outline] = relationship(back_populates="scenes")
    narration: Mapped[Optional["Narration"]] = relationship(back_populates="scene", uselist=False)


class Narration(Base):
    __tablename__ = "narration"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    scene_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("scene.id", ondelete="CASCADE"),
                                          nullable=False, unique=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    char_count: Mapped[int] = mapped_column(Integer, nullable=False)
    est_duration_sec: Mapped[Decimal] = mapped_column(Numeric(5, 1), nullable=False)
    is_edited: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("FALSE"))
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=NOW_ON_UPDATE)

    scene: Mapped[Scene] = relationship(back_populates="narration")
    cues: Mapped[list["SubtitleCue"]] = relationship(order_by="SubtitleCue.seq", back_populates="narration",
                                                     cascade="all, delete-orphan")


class SubtitleCue(Base):
    __tablename__ = "subtitle_cue"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    narration_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("narration.id", ondelete="CASCADE"),
                                              nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    start_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    end_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    body: Mapped[str] = mapped_column(String(100), nullable=False)

    narration: Mapped[Narration] = relationship(back_populates="cues")


class QuizItem(Base):
    __tablename__ = "quiz_item"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    outline_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("outline.id", ondelete="CASCADE"), nullable=False)
    scene_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("scene.id", ondelete="SET NULL"))
    question: Mapped[str] = mapped_column(String(500), nullable=False)
    choices: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    answer_index: Mapped[int] = mapped_column(TINYINT, nullable=False)
    explanation: Mapped[Optional[str]] = mapped_column(Text)


# ---------- 매뉴얼형 결과 ----------
class Manual(Base):
    __tablename__ = "manual"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("generation_run.id", ondelete="CASCADE"), nullable=False)
    project_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("project.id", ondelete="CASCADE"), nullable=False)
    audience: Mapped[str] = mapped_column(String(100), nullable=False)
    difficulty: Mapped[str] = mapped_column(_enum(*DIFFICULTY, name="manual_difficulty"), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    intro: Mapped[Optional[str]] = mapped_column(Text)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("TRUE"))
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=NOW)

    steps: Mapped[list["ManualStep"]] = relationship(order_by="ManualStep.seq", back_populates="manual")
    cautions: Mapped[list["Caution"]] = relationship(order_by="Caution.id", back_populates="manual")
    schedule: Mapped[list["ScheduleItem"]] = relationship(order_by="ScheduleItem.seq", back_populates="manual")


class ManualStep(Base):
    __tablename__ = "manual_step"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    manual_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("manual.id", ondelete="CASCADE"), nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    instruction: Mapped[str] = mapped_column(Text, nullable=False)
    tip: Mapped[Optional[str]] = mapped_column(Text)
    source_paragraphs: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    edited_fields: Mapped[Optional[list[str]]] = mapped_column(JSON)

    manual: Mapped[Manual] = relationship(back_populates="steps")


class Caution(Base):
    __tablename__ = "caution"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    manual_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("manual.id", ondelete="CASCADE"))
    scene_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("scene.id", ondelete="CASCADE"))
    severity: Mapped[str] = mapped_column(_enum("info", "warning", "danger", name="caution_severity"), nullable=False)
    body: Mapped[str] = mapped_column(String(500), nullable=False)
    source: Mapped[str] = mapped_column(_enum("ai", "rule", "user", name="caution_source"), nullable=False)

    manual: Mapped[Optional[Manual]] = relationship(back_populates="cautions")


class ScheduleItem(Base):
    __tablename__ = "schedule_item"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    manual_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("manual.id", ondelete="CASCADE"), nullable=False)
    manual_step_id: Mapped[Optional[int]] = mapped_column(BigInteger,
                                                          ForeignKey("manual_step.id", ondelete="SET NULL"))
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    start_offset_day: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    duration_days: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    interval_days: Mapped[Optional[int]] = mapped_column(Integer)
    note: Mapped[Optional[str]] = mapped_column(String(500))
    source: Mapped[str] = mapped_column(_enum("ai", "user", name="schedule_source"), nullable=False)

    manual: Mapped[Manual] = relationship(back_populates="schedule")


# ---------- 검수와 수정 이력 ----------
class ReviewCheck(Base):
    __tablename__ = "review_check"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("generation_run.id", ondelete="CASCADE"), nullable=False)
    check_code: Mapped[str] = mapped_column(String(10), nullable=False)
    target_type: Mapped[Optional[str]] = mapped_column(String(30))
    target_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    result: Mapped[str] = mapped_column(_enum("pass", "warn", "fail", "unchecked", name="check_result"),
                                        nullable=False)
    message: Mapped[Optional[str]] = mapped_column(String(500))
    checked_by: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("app_user.id"))
    checked_at: Mapped[Optional[datetime]] = mapped_column(DateTime)


class Revision(Base):
    __tablename__ = "revision"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    entity_type: Mapped[str] = mapped_column(String(30), nullable=False)
    entity_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    field_name: Mapped[str] = mapped_column(String(50), nullable=False)
    before_value: Mapped[Optional[str]] = mapped_column(MEDIUMTEXT)
    after_value: Mapped[Optional[str]] = mapped_column(MEDIUMTEXT)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("app_user.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=NOW)


# ---------- 수정 요청 에이전트(설계서 13절) ----------
class EditRequest(Base):
    __tablename__ = "edit_request"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("project.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("app_user.id"), nullable=False)
    request_text: Mapped[str] = mapped_column(String(1000), nullable=False)
    status: Mapped[str] = mapped_column(
        _enum("running", "proposed", "refused", "limit", "failed", "done", name="edit_status"),
        nullable=False, server_default="running")
    tool_calls: Mapped[int] = mapped_column(TINYINT, nullable=False, server_default="0")
    summary: Mapped[Optional[str]] = mapped_column(Text)
    llm_model: Mapped[str] = mapped_column(String(80), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=NOW)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime)


class AgentAction(Base):
    __tablename__ = "agent_action"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    edit_request_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("edit_request.id", ondelete="CASCADE"),
                                                 nullable=False)
    seq: Mapped[int] = mapped_column(TINYINT, nullable=False)
    tool_name: Mapped[str] = mapped_column(String(50), nullable=False)
    arguments: Mapped[Any] = mapped_column(JSON, nullable=False)
    result_summary: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[str] = mapped_column(_enum("ok", "error", "blocked", name="action_status"), nullable=False)
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=NOW)


class ChangeProposal(Base):
    __tablename__ = "change_proposal"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    edit_request_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("edit_request.id", ondelete="CASCADE"),
                                                 nullable=False)
    target_type: Mapped[str] = mapped_column(_enum("scene", "narration", "manual_step", name="proposal_target"),
                                             nullable=False)
    target_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    field_name: Mapped[str] = mapped_column(String(50), nullable=False)
    before_value: Mapped[Optional[str]] = mapped_column(MEDIUMTEXT)
    after_value: Mapped[str] = mapped_column(MEDIUMTEXT, nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(String(500))
    user_edited: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("FALSE"))
    status: Mapped[str] = mapped_column(_enum("pending", "accepted", "rejected", name="proposal_status"),
                                        nullable=False, server_default="pending")
    decided_by: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("app_user.id"))
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
