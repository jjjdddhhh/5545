# runner.py : 생성 워크플로의 단계 실행기(설계서 4절, 8절).
# 코드가 정한 7단계를 순서대로 실행한다. LLM이 다음 행동을 고르지 않으므로 "에이전트"가 아니라 워크플로다(결정 1).
#
#   1 텍스트 정제(clean)  2 분량 계산(budget)  3 구조화·구성안(outline)  4 장면 상세(scene_detail)
#   5a 내레이션·자막(narration, 영상형)  5b 맞춤 매뉴얼·일정(manual, 매뉴얼형)  6 검수(checks)  7 저장(save)
#
# 실행 방식
# - POST /api/projects/{id}/runs가 start_run()으로 generation_run을 만들고 202와 run_id를 바로 돌려준다.
# - 실제 생성은 launch()가 만든 별도 스레드에서 execute_run()이 한다. Ollama 클라이언트가 동기 방식이라
#   이벤트 루프를 막지 않으려면 스레드가 필요하다.
# - 스레드는 자기 DB 세션을 따로 연다(요청의 세션은 응답과 함께 닫히므로 쓸 수 없다).
# - 단계 시작·완료·오류와 LLM 호출 하나하나를 events.hub로 SSE에 넘기고, 같은 내용을 DB(generation_run,
#   agent_step_log)에도 남겨, 화면을 닫았다 다시 열어도 진행 위치를 복원할 수 있게 한다.
import threading
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Optional

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db import models as m
from app.db import session as db_session
from app.llm import llm_client
from app.llm.prompt_store import active_prompt
from app.pipeline import budget as budget_mod
from app.pipeline import checks
from app.pipeline.events import hub
from app.pipeline.outline import generate_outline
from app.pipeline.scene_detail import SceneInput, generate_scene_detail

# 단계 이름(이벤트와 current_stage에 쓰는 키)과 화면에 보여 줄 한국어 이름. 순서가 곧 실행 순서다.
STAGES: list[tuple[str, str]] = [
    ("clean", "텍스트 정제"),
    ("budget", "분량 계산"),
    ("outline", "구조화·구성안"),
    ("scene_detail", "장면 상세"),
    ("narration", "내레이션·자막"),
    ("manual", "맞춤 매뉴얼·일정"),
    ("checks", "검수"),
    ("save", "저장"),
]
STAGE_LABEL = dict(STAGES)
# 코드만 실행하는 단계. 이 단계들은 agent_step_log에 prompt_template_id 없이 한 줄씩 남긴다(설계서 7절 "코드 단계는 NULL").
CODE_STAGES = {"clean", "budget", "checks", "save"}


def run_key(run_id: int) -> str:
    """events.hub에서 이 실행의 이벤트를 찾는 키."""
    return f"run:{run_id}"


def stages_for(content_type: str) -> list[str]:
    """콘텐츠 유형에 따라 실행할 단계 목록. 4단계까지는 공유하고 5단계만 갈라진다(설계서 4절)."""
    keys = [k for k, _ in STAGES]
    if content_type == "video":
        keys.remove("manual")
    elif content_type == "manual":
        keys.remove("narration")
    return keys


class RunError(Exception):
    """실행 시작 조건이 맞지 않을 때(원고나 설정이 없음, 이미 실행 중) 올린다. API가 400·409로 바꾼다."""
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


# ---------- LLM 호출 기록기 ----------
class DbRecorder:
    """llm_step.call_llm이 시도마다 부르는 기록기. agent_step_log에 한 줄씩 쓰고 SSE로도 알린다."""

    def __init__(self, db: Session, run_id: int):
        self.db = db
        self.run_id = run_id
        self.truncation_hits = 0   # 구성안 단계의 잘림 대비 판단에 쓴다(StepRecorder 프로토콜)

    def record(self, stage: str, template_id: Optional[int], log: dict, input_json: Any, output_json: Any) -> None:
        if log.get("truncation_risk"):
            self.truncation_hits += 1
        self.db.add(m.AgentStepLog(
            run_id=self.run_id, stage=stage, prompt_template_id=template_id,
            attempt=log.get("attempt", 1), input_json=input_json, output_json=output_json,
            status=log.get("status", "ok"), tokens_in=log.get("tokens_in"), tokens_out=log.get("tokens_out"),
            latency_ms=log.get("latency_ms")))
        self.db.commit()   # 시도마다 바로 커밋해, 실행 도중 서버가 꺼져도 그때까지의 로그가 남게 한다
        hub.publish(run_key(self.run_id), {
            "type": "llm_call", "stage": stage, "attempt": log.get("attempt"), "status": log.get("status"),
            "tokens_in": log.get("tokens_in"), "tokens_out": log.get("tokens_out"),
            "latency_ms": log.get("latency_ms"), "truncation_risk": bool(log.get("truncation_risk")),
            "target": (input_json or {}).get("target") if isinstance(input_json, dict) else None})


# ---------- 실행 문맥 ----------
@dataclass
class RunContext:
    db: Session
    run: m.GenerationRun
    setting: m.GenerationSetting
    source: m.SourceDocument
    recorder: DbRecorder
    paragraphs: list[dict] = field(default_factory=list)
    paragraphs_by_id: dict[str, dict] = field(default_factory=dict)
    budget: Optional[budget_mod.Budget] = None
    outline: Optional[m.Outline] = None
    manual: Optional[m.Manual] = None
    # 생성 단계 안에서 이미 돌린 검수 가운데 "1회 다시 요청한 뒤에도 남은 실패"와 "생성 자체 실패(C01)".
    # 6단계가 최종 결과를 저장할 때 이 기록을 보고 "다시 요청했지만 통과하지 못함"을 메시지에 붙인다.
    notes: list[checks.CheckResult] = field(default_factory=list)
    # 1회 다시 요청한 대상 (검사 코드, 대상 종류, 대상 id). 6단계 메시지에 재요청 여부를 표시하는 데 쓴다.
    retried: set[tuple[str, str, Optional[int]]] = field(default_factory=set)

    @property
    def key(self) -> str:
        return run_key(self.run.id)

    def publish(self, event: dict) -> None:
        hub.publish(self.key, event)

    def scenes(self) -> list[m.Scene]:
        return list(self.outline.scenes) if self.outline else []


# ---------- 실행 시작 ----------
def start_run(db: Session, project_id: int) -> m.GenerationRun:
    """generation_run을 만들고 프로젝트를 생성 중으로 바꾼다. 스레드는 launch()로 따로 띄운다.
    원고와 설정은 가장 최근 것을 쓴다. 이미 진행 중인 실행이 있으면 409로 막는다(GPU 하나를 두 실행이 나눠 쓰지 않게)."""
    from app.api import deps   # api 계층과의 순환 import를 피하려고 함수 안에서 불러온다
    project = deps.project_or_404(db, project_id)
    source = deps.latest_source(db, project_id)
    if source is None:
        raise RunError("원고가 없습니다. 자료 입력 화면에서 원고를 먼저 넣어 주세요.")
    setting = deps.latest_setting(db, project_id)
    if setting is None:
        raise RunError("생성 조건이 없습니다. 조건 설정 화면에서 먼저 저장해 주세요.")
    busy = db.scalar(select(m.GenerationRun.id).where(m.GenerationRun.project_id == project_id,
                                                      m.GenerationRun.status.in_(("queued", "running"))))
    if busy:
        raise RunError(f"이미 진행 중인 생성이 있습니다(실행 {busy}). 끝난 뒤 다시 시도해 주세요.", 409)
    run = m.GenerationRun(project_id=project_id, setting_id=setting.id, source_id=source.id,
                          status="queued", llm_model=llm_client.MODEL)
    db.add(run)
    project.status = "generating"
    db.commit()
    return run


def launch(run_id: int) -> threading.Thread:
    """execute_run을 데몬 스레드로 띄운다. 데몬이므로 서버를 끄면 함께 멈추고, 다음 시작 때 recover_interrupted()가 정리한다."""
    t = threading.Thread(target=execute_run, args=(run_id,), name=f"run-{run_id}", daemon=True)
    t.start()
    return t


def recover_interrupted(db: Session) -> int:
    """서버가 꺼질 때 진행 중이던 실행은 다시 이어 갈 수 없으므로 실패로 표시한다. 앱 시작 때 한 번 부른다.
    표시하지 않으면 화면이 영원히 "진행 중"을 보여 주고, 같은 프로젝트에서 새 실행도 막힌다(start_run의 409)."""
    msg = "서버가 다시 시작되어 생성이 중단되었습니다. 다시 생성해 주세요."
    res = db.execute(update(m.GenerationRun).where(m.GenerationRun.status.in_(("queued", "running")))
                     .values(status="failed", error_message=msg, finished_at=datetime.now()))
    db.execute(update(m.Project).where(m.Project.status == "generating").values(status="error"))
    db.commit()
    return res.rowcount or 0


# ---------- 실행 본체 ----------
def execute_run(run_id: int) -> None:
    """스레드에서 도는 실행 본체. 어떤 예외가 나도 실행 상태를 failed로 남기고 SSE에 알린 뒤 끝난다."""
    db = db_session.SessionLocal()
    try:
        run = db.get(m.GenerationRun, run_id)
        if run is None:
            return
        ctx = RunContext(db=db, run=run, setting=db.get(m.GenerationSetting, run.setting_id),
                         source=db.get(m.SourceDocument, run.source_id), recorder=DbRecorder(db, run_id))
        run.status, run.started_at = "running", datetime.now()
        db.commit()
        keys = stages_for(ctx.setting.content_type)
        ctx.publish({"type": "run_start", "run_id": run_id,
                     "stages": [{"key": k, "label": STAGE_LABEL[k]} for k in keys]})
        for i, key in enumerate(keys, 1):
            _run_stage(ctx, key, i, len(keys))
        ctx.publish({"type": "done", "run_id": run_id, "status": "done"})
    except Exception as exc:  # 어떤 단계에서 무슨 오류가 나도 실행을 실패로 마무리한다
        db.rollback()   # 반쯤 쓴 내용이 커밋되지 않게 되돌린 뒤 실패 상태만 기록한다
        _fail(db, run_id, exc)
    finally:
        db.close()


def _run_stage(ctx: RunContext, key: str, index: int, total: int) -> None:
    """단계 하나를 실행하고 시작·완료 이벤트와 로그를 남긴다."""
    ctx.run.current_stage = key
    ctx.db.commit()
    ctx.publish({"type": "stage_start", "stage": key, "label": STAGE_LABEL[key], "index": index, "total": total})
    started = time.perf_counter()
    detail = STAGE_FUNCS[key](ctx) or {}
    latency = int((time.perf_counter() - started) * 1000)
    if key in CODE_STAGES:
        ctx.db.add(m.AgentStepLog(run_id=ctx.run.id, stage=key, prompt_template_id=None, attempt=1,
                                  input_json=None, output_json=detail, status="ok", latency_ms=latency))
    ctx.db.commit()
    ctx.publish({"type": "stage_done", "stage": key, "label": STAGE_LABEL[key], "index": index, "total": total,
                 "latency_ms": latency, "detail": detail})


def _fail(db: Session, run_id: int, exc: Exception) -> None:
    run = db.get(m.GenerationRun, run_id)
    stage = run.current_stage if run else None
    message = f"{STAGE_LABEL.get(stage, stage or '준비')} 단계에서 실패했습니다: {exc}"
    if run is not None:
        run.status, run.finished_at, run.error_message = "failed", datetime.now(), message[:5000]
        project = db.get(m.Project, run.project_id)
        if project is not None:
            project.status = "error"
        db.commit()
    hub.publish(run_key(run_id), {"type": "stage_error", "stage": stage, "label": STAGE_LABEL.get(stage, stage),
                                  "message": message, "trace": traceback.format_exc(limit=3)})
    hub.publish(run_key(run_id), {"type": "done", "run_id": run_id, "status": "failed", "message": message})


# ---------- 1단계 텍스트 정제 ----------
def stage_clean(ctx: RunContext) -> dict:
    """원고는 업로드할 때 이미 text_cleaner로 정제해 문단 목록으로 저장했다. 여기서는 그 목록을 읽어 확인만 한다.
    업로드 뒤 사용자가 문단을 합치거나 나눴다면 그 결과가 들어 있다."""
    ctx.paragraphs = list(ctx.source.paragraphs or [])
    if not ctx.paragraphs:
        raise RuntimeError("원고 문단이 비어 있습니다.")
    ctx.paragraphs_by_id = {p["id"]: p for p in ctx.paragraphs}
    return {"paragraphs": len(ctx.paragraphs), "chars": ctx.source.char_count,
            "headings": sum(p["kind"] == "heading" for p in ctx.paragraphs),
            "tables": sum(p["kind"] == "table" for p in ctx.paragraphs)}


# ---------- 2단계 분량 계산 ----------
def stage_budget(ctx: RunContext) -> dict:
    s = ctx.setting
    ctx.budget = budget_mod.compute_budget(s.target_duration_sec, s.scene_count, s.scene_default_sec, s.narration_cpm)
    return ctx.budget.as_dict()


# ---------- 3단계 구조화·구성안 ----------
def stage_outline(ctx: RunContext) -> dict:
    prompt = active_prompt(ctx.db, "outline")
    res = generate_outline(ctx.recorder, prompt, ctx.setting, ctx.paragraphs, ctx.budget.scene_count)
    out = res.outline
    if not out.scenes:
        raise RuntimeError("구성안에 장면이 하나도 없습니다.")
    if len(out.scenes) != ctx.budget.scene_count:
        # 다시 요청해도 장면 수가 다르면(C02 경고) 모델이 만든 장면을 버리지 않고, 전체 분량은 지킨 채
        # 실제 장면 수로 시간과 글자 수를 다시 나눈다. 숫자는 언제나 코드가 정한다(결정 2).
        ctx.budget = budget_mod.compute_budget(ctx.budget.total_sec, len(out.scenes),
                                               ctx.setting.scene_default_sec, ctx.setting.narration_cpm)
    outline = m.Outline(run_id=ctx.run.id, project_id=ctx.run.project_id, title=out.title[:200],
                        summary=out.summary, learning_objectives=list(out.learning_objectives),
                        is_current=False)   # 7단계(저장)에서 현재 결과로 바꾼다. 그 전까지 화면은 이전 결과를 보여 준다
    ctx.db.add(outline)
    for s, dur, cb in zip(out.scenes, ctx.budget.durations, ctx.budget.char_budgets):
        ctx.db.add(m.Scene(outline=outline, seq=s.seq, title=s.title[:200], key_point=s.key_point[:500],
                           source_paragraphs=list(s.source_paragraphs), duration_sec=dur, char_budget=cb,
                           edited_fields=[]))
    ctx.db.commit()
    ctx.outline = outline
    # 다시 요청한 뒤에도 남은 실패를 6단계로 넘긴다. 장면 seq를 DB id로 바꿔 화면의 장면 점과 연결한다.
    seq_to_id = {sc.seq: sc.id for sc in ctx.scenes()}
    for f in res.failures:
        if f.target_type == "scene":
            f.target_ref = seq_to_id.get(f.data.get("seq"), f.target_ref)
        ctx.notes.append(f)
    if res.retried:
        ctx.retried.update({("C02", "outline", None), ("C11", "outline", None)})
        ctx.retried.update(("C03", "scene", sc.id) for sc in ctx.scenes())
    return {"title": outline.title, "scenes": len(out.scenes), "retried": res.retried,
            "summarized": res.summarized, "remaining_failures": [f.message for f in res.failures]}


# ---------- 4단계 장면 상세 ----------
def stage_scene_detail(ctx: RunContext) -> dict:
    """장면마다 따로 부른다. 한 장면이 실패해도 실행 전체를 멈추지 않고, 그 장면은 비워 둔 채 C01 실패로 남긴다.
    사용자가 나중에 "이 장면만 다시 생성"으로 채울 수 있기 때문이다."""
    prompt = active_prompt(ctx.db, "scene_detail")
    scenes = ctx.scenes()
    failed = 0
    for i, sc in enumerate(scenes, 1):
        ctx.publish({"type": "progress", "stage": "scene_detail", "current": i, "total": len(scenes),
                     "scene_id": sc.id, "title": sc.title})
        try:
            res = generate_scene_detail(ctx.recorder, prompt, ctx.setting, ctx.outline.title,
                                        scene_input(sc), ctx.paragraphs_by_id, scene_ref=sc.id)
        except llm_client.GenerationError as exc:
            failed += 1
            ctx.notes.append(checks.CheckResult("C01", checks.FAIL, f"장면 {sc.seq} 상세 생성 실패: {exc}",
                                                "scene", sc.id))
            continue
        apply_detail(sc, res.detail)
        ctx.db.commit()
        ctx.notes.extend(res.failures)
        if res.retried:
            ctx.retried.add(("C11", "scene", sc.id))
    return {"scenes": len(scenes), "failed": failed}


def scene_input(sc: m.Scene) -> SceneInput:
    """DB의 장면을 장면 상세 단계의 입력으로 바꾼다. 사용자가 고친 상세 필드는 고정값으로 넘긴다."""
    fixed = {f: getattr(sc, f) for f in (sc.edited_fields or []) if f in
             ("screen_description", "visual_suggestion", "on_screen_text")}
    return SceneInput(seq=sc.seq, title=sc.title, key_point=sc.key_point, duration_sec=sc.duration_sec,
                      source_paragraphs=list(sc.source_paragraphs or []), fixed=fixed)


def apply_detail(sc: m.Scene, detail) -> None:
    """LLM 결과를 장면에 쓴다. 사용자가 고친 필드는 건너뛴다(설계서 10절 규칙 2)."""
    edited = set(sc.edited_fields or [])
    for f in ("screen_description", "visual_suggestion", "on_screen_text"):
        if f not in edited:
            setattr(sc, f, getattr(detail, f))


# ---------- 5a, 5b, 6단계는 다음 구현 단계에서 채운다 ----------
def stage_narration(ctx: RunContext) -> dict:
    return {"skipped": "단계 3에서 구현한다"}


def stage_manual(ctx: RunContext) -> dict:
    return {"skipped": "단계 4에서 구현한다"}


def stage_checks(ctx: RunContext) -> dict:
    """지금은 생성 단계에서 넘어온 기록만 저장한다. 단계 5에서 C01~C12 전체로 바꾼다."""
    for n in ctx.notes:
        ctx.db.add(m.ReviewCheck(run_id=ctx.run.id, check_code=n.code, target_type=n.target_type,
                                 target_id=n.target_ref, result=n.result if n.code == "C01" else checks.WARN,
                                 message=n.message[:500]))
    ctx.db.commit()
    return {"notes": len(ctx.notes)}


# ---------- 7단계 저장 ----------
def stage_save(ctx: RunContext) -> dict:
    """이번 실행의 결과를 현재 결과로 바꾸고, 이전 결과는 is_current만 false로 바꿔 보존한다(설계서 10절 규칙 4)."""
    pid = ctx.run.project_id
    if ctx.outline is not None:
        ctx.db.execute(update(m.Outline).where(m.Outline.project_id == pid, m.Outline.id != ctx.outline.id)
                       .values(is_current=False))
        ctx.outline.is_current = True
    if ctx.manual is not None:
        ctx.db.execute(update(m.Manual).where(m.Manual.project_id == pid, m.Manual.id != ctx.manual.id)
                       .values(is_current=False))
        ctx.manual.is_current = True
    ctx.run.status, ctx.run.finished_at, ctx.run.current_stage = "done", datetime.now(), "save"
    project = ctx.db.get(m.Project, pid)
    project.status = "ready"
    ctx.db.commit()
    return {"outline_id": ctx.outline.id if ctx.outline else None,
            "manual_id": ctx.manual.id if ctx.manual else None}


STAGE_FUNCS: dict[str, Callable[[RunContext], dict]] = {
    "clean": stage_clean, "budget": stage_budget, "outline": stage_outline, "scene_detail": stage_scene_detail,
    "narration": stage_narration, "manual": stage_manual, "checks": stage_checks, "save": stage_save,
}


# ---------- 다시 연결했을 때 보여 줄 현재 상태 ----------
def run_snapshot(db: Session, run: m.GenerationRun) -> dict:
    """DB만 보고 실행의 단계별 상태를 다시 만든다. SSE에 처음 연결하거나 다시 연결할 때 맨 먼저 보낸다.
    메모리의 이벤트는 서버를 다시 켜면 사라지지만, 이 상태는 DB에서 언제든 다시 만들 수 있다(설계서 8절)."""
    setting = db.get(m.GenerationSetting, run.setting_id)
    keys = stages_for(setting.content_type if setting else "both")
    cur = keys.index(run.current_stage) if run.current_stage in keys else -1
    stages = []
    for i, k in enumerate(keys):
        if run.status == "done":
            status = "done"
        elif run.status == "queued" or cur < 0:
            status = "pending"
        elif i < cur:
            status = "done"
        elif i == cur:
            status = "failed" if run.status == "failed" else "running"
        else:
            status = "pending"
        stages.append({"key": k, "label": STAGE_LABEL[k], "status": status})

    # 단계별 LLM 호출 통계. 화면의 "장면 상세 3/5" 같은 표시와 실패 원인 파악에 쓴다.
    rows = db.execute(select(m.AgentStepLog.stage, m.AgentStepLog.status, m.AgentStepLog.tokens_in,
                             m.AgentStepLog.tokens_out, m.AgentStepLog.latency_ms)
                      .where(m.AgentStepLog.run_id == run.id)).all()
    stats: dict[str, dict] = {}
    for stage, status, tin, tout, lat in rows:
        st = stats.setdefault(stage, {"calls": 0, "ok": 0, "retry": 0, "failed": 0,
                                      "tokens_in": 0, "tokens_out": 0, "latency_ms": 0})
        st["calls"] += 1
        st[status] += 1
        st["tokens_in"] += tin or 0
        st["tokens_out"] += tout or 0
        st["latency_ms"] += lat or 0
    for s in stages:
        s["stats"] = stats.get(s["key"])
    return {"type": "snapshot", "run_id": run.id, "project_id": run.project_id, "status": run.status,
            "current_stage": run.current_stage, "error_message": run.error_message,
            "llm_model": run.llm_model, "stages": stages}
