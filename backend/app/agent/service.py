# service.py : 수정 요청 에이전트를 API에 잇는 실행 계층(설계서 13절).
# - start_edit_request(): edit_request 행을 만들고 백그라운드 스레드에서 에이전트를 돌린다(202).
# - TracingEditAgent: edit_agent.EditAgent를 그대로 쓰되, 도구를 하나 실행할 때마다 agent_action에 저장하고
#   SSE로 알린다(트레이싱). 에이전트의 판단 로직(도구 선택, 가드레일, 한도)은 edit_agent.py 그대로다.
# - apply_proposal()/reject_proposal(): 사용자가 제안을 승인하거나 거절했을 때의 DB 반영.
#   승인하면 필드를 바꾸고 revision을 남기며, 내레이션 제안이면 자막을 코드로 다시 나눈다.
import json
import threading
import time
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import config
from app.agent.edit_agent import EditAgent
from app.agent.repo import SqlRepo, scene_map_note
from app.api import deps
from app.db import models as m
from app.db import session as db_session
from app.llm import llm_client
from app.pipeline import persist, review
from app.pipeline.events import hub
from app.pipeline.llm_step import LLM_LOCK

# 에이전트가 이 필드 이름으로 제안하면 어떤 DB 컬럼을 바꾸는지. edit_agent의 SCENE_FIELDS, STEP_FIELDS와 같다.
FIELD_LABEL = {"title": "제목", "screen_description": "화면 설명", "visual_suggestion": "시각자료 제안",
               "on_screen_text": "화면 텍스트", "body": "내레이션", "instruction": "지시", "tip": "도움말"}
# 도구 이름의 한국어 설명. 화면의 "에이전트가 부르는 도구" 진행 표시에 쓴다.
TOOL_LABEL = {"get_project_overview": "전체 구성 조회", "get_scene": "장면 조회", "get_source": "원고 문단 조회",
              "propose_scene_edit": "장면 수정 제안", "propose_narration_edit": "내레이션 수정 제안",
              "propose_manual_edit": "매뉴얼 단계 수정 제안", "check_proposals": "제안 검수"}


def edit_key(edit_request_id: int) -> str:
    return f"edit:{edit_request_id}"


class EditRequestError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


# ---------- 트레이싱하는 에이전트 ----------
class TracingEditAgent(EditAgent):
    """도구 호출마다 agent_action에 바로 저장하고 SSE로 알린다. 실행 도중 화면을 다시 열어도 지금까지의 호출을 보여 줄 수 있다.
    EditAgent.run()이 끝난 뒤 result.actions에도 같은 내용이 쌓이지만, 저장은 여기서 한 번만 한다."""

    def __init__(self, repo: SqlRepo, project_id: int, db: Session, edit_request_id: int):
        super().__init__(repo, project_id)
        self.db = db
        self.edit_request_id = edit_request_id

    def _execute(self, name: str, args: dict) -> tuple[Any, str]:
        started = time.perf_counter()
        output, status = super()._execute(name, args)
        seq = len(self.result.actions) + 1        # run()이 이 호출을 result.actions에 넣기 직전이므로 +1이다
        summary = json.dumps(output, ensure_ascii=False, default=str)[:500]
        latency = int((time.perf_counter() - started) * 1000)
        self.db.add(m.AgentAction(edit_request_id=self.edit_request_id, seq=seq, tool_name=name[:50],
                                  arguments=_jsonable(args), result_summary=summary, status=status,
                                  latency_ms=latency))
        req = self.db.get(m.EditRequest, self.edit_request_id)
        req.tool_calls = seq
        self.db.commit()
        hub.publish(edit_key(self.edit_request_id), {
            "type": "tool", "seq": seq, "tool_name": name, "label": TOOL_LABEL.get(name, name),
            "arguments": _jsonable(args), "status": status, "result_summary": summary[:200], "latency_ms": latency})
        return output, status


def _jsonable(value: Any) -> Any:
    """LLM이 넘긴 인자를 JSON 컬럼에 넣을 수 있는 모양으로 바꾼다(드물게 섞이는 비표준 객체를 문자열로)."""
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


# ---------- 시작과 실행 ----------
def start_edit_request(db: Session, project_id: int, request_text: str) -> m.EditRequest:
    """수정 요청을 접수한다. 고칠 결과(현재 구성안이나 매뉴얼)가 없으면 400으로 막는다."""
    deps.project_or_404(db, project_id)
    if deps.current_outline(db, project_id) is None and deps.current_manual(db, project_id) is None:
        raise EditRequestError("고칠 결과가 없습니다. 먼저 콘텐츠를 생성해 주세요.")
    req = m.EditRequest(project_id=project_id, user_id=config.DEFAULT_USER_ID, request_text=request_text[:1000],
                        status="running", llm_model=llm_client.MODEL)
    db.add(req)
    db.commit()
    return req


def launch(edit_request_id: int) -> threading.Thread:
    t = threading.Thread(target=run_edit_request, args=(edit_request_id,), name=f"edit-{edit_request_id}", daemon=True)
    t.start()
    return t


def run_edit_request(edit_request_id: int) -> None:
    """스레드에서 에이전트를 돌리고 결과(상태, 요약, 제안)를 저장한다.
    LLM 잠금은 요청 하나가 끝날 때까지 잡는다. 에이전트는 도구 결과를 보고 곧바로 다음 LLM 호출을 하므로,
    호출마다 잠금을 놓으면 생성 실행과 번갈아 돌며 둘 다 느려지기 때문이다(GPU 하나, 설계서 12절)."""
    db = db_session.SessionLocal()
    key = edit_key(edit_request_id)
    try:
        req = db.get(m.EditRequest, edit_request_id)
        if req is None:
            return
        repo = SqlRepo(db, req.project_id)
        agent = TracingEditAgent(repo, req.project_id, db, edit_request_id)
        note = scene_map_note(repo)
        text = req.request_text + (f"\n\n{note}" if note else "")
        hub.publish(key, {"type": "start", "edit_request_id": edit_request_id})
        with LLM_LOCK:
            result = agent.run(text)
        saved = save_proposals(db, req, repo, result.proposals)
        req.status = result.status
        req.summary = result.summary
        req.tool_calls = len(result.actions)
        req.finished_at = datetime.now()
        db.commit()
        hub.publish(key, {"type": "done", "status": req.status, "summary": req.summary,
                          "proposal_ids": [p.id for p in saved]})
    except Exception as exc:  # Ollama 연결 실패 등. 요청을 실패로 남기고 화면에 사유를 보낸다
        db.rollback()
        req = db.get(m.EditRequest, edit_request_id)
        message = f"수정 요청을 처리하지 못했습니다: {exc}"
        if req is not None:
            req.status, req.summary, req.finished_at = "failed", message[:5000], datetime.now()
            db.commit()
        hub.publish(key, {"type": "done", "status": "failed", "summary": message, "proposal_ids": []})
    finally:
        db.close()


def save_proposals(db: Session, req: m.EditRequest, repo: SqlRepo, proposals: list[dict]) -> list[m.ChangeProposal]:
    """에이전트의 제안을 change_proposal에 저장한다.
    edit_agent는 내레이션 제안의 target_id에 장면 id를 넣으므로, 저장할 때 그 장면의 내레이션 id로 바꾼다.
    내레이션이 아직 없는 장면(매뉴얼형만 만든 경우)이면 빈 내레이션을 만들어 승인 때 채울 자리를 둔다."""
    rows = []
    for p in proposals:
        target_type, target_id = p["target_type"], int(p["target_id"])
        if target_type == "narration":
            scene = repo._scene(target_id)
            if scene.narration is None:
                persist.save_narration(db, scene, "", repo.setting)
                db.flush()
            target_id = scene.narration.id
        row = m.ChangeProposal(edit_request_id=req.id, target_type=target_type, target_id=target_id,
                               field_name=p["field_name"], before_value=p.get("before_value"),
                               after_value=p["after_value"], reason=(p.get("reason") or "")[:500],
                               user_edited=bool(p.get("user_edited")), status="pending")
        db.add(row)
        rows.append(row)
    db.flush()
    return rows


# ---------- 승인과 거절 ----------
def current_value(db: Session, p: m.ChangeProposal) -> Optional[str]:
    """제안 대상 필드의 지금 값."""
    if p.target_type == "narration":
        narr = db.get(m.Narration, p.target_id)
        return narr.body if narr else None
    model = m.Scene if p.target_type == "scene" else m.ManualStep
    obj = db.get(model, p.target_id)
    return getattr(obj, p.field_name) if obj else None


def apply_proposal(db: Session, p: m.ChangeProposal, user_id: int) -> None:
    """제안을 반영한다. 순서: 지금 값이 제안 때의 값과 같은지 확인, 필드 바꾸기, revision, edited_fields, 다시 검수.
    제안을 만든 뒤 사용자가 같은 필드를 직접 고쳤다면 그 수정을 모르고 덮어쓰지 않도록 409로 막는다."""
    if p.status != "pending":
        raise EditRequestError("이미 처리한 제안입니다.", 409)
    now = current_value(db, p)
    if (now or "") != (p.before_value or ""):
        raise EditRequestError("제안을 만든 뒤 내용이 바뀌었습니다. 다시 수정 요청을 해 주세요.", 409)

    if p.target_type == "narration":
        narr = db.get(m.Narration, p.target_id)
        persist.add_revision(db, "narration", narr.id, "body", narr.body, p.after_value, user_id)
        # 승인한 내레이션도 사람이 고른 내용이므로 is_edited로 표시해 재생성에서 보호한다.
        persist.save_narration(db, narr.scene, p.after_value, persist.setting_of_scene(db, narr.scene), is_edited=True)
        run_id = narr.scene.outline.run_id
    else:
        model = m.Scene if p.target_type == "scene" else m.ManualStep
        obj = db.get(model, p.target_id)
        persist.add_revision(db, p.target_type, obj.id, p.field_name, getattr(obj, p.field_name), p.after_value, user_id)
        value = p.after_value[:300] if p.field_name == "on_screen_text" else p.after_value
        value = value[:200] if p.field_name == "title" else value
        setattr(obj, p.field_name, value)
        persist.mark_edited(obj, p.field_name)   # 승인한 필드도 재생성에서 덮어쓰지 않는다
        run_id = obj.outline.run_id if p.target_type == "scene" else obj.manual.run_id

    p.status, p.decided_by, p.decided_at = "accepted", user_id, datetime.now()
    _close_if_decided(db, p.edit_request_id)
    db.commit()
    review.recheck_for_run_id(db, run_id)


def reject_proposal(db: Session, p: m.ChangeProposal, user_id: int, reason: Optional[str]) -> None:
    """제안을 거절하고 원래 내용을 유지한다. 거절 사유는 change_proposal에 칸이 없어 edit_request.summary 끝에 덧붙인다."""
    if p.status != "pending":
        raise EditRequestError("이미 처리한 제안입니다.", 409)
    p.status, p.decided_by, p.decided_at = "rejected", user_id, datetime.now()
    if reason and reason.strip():
        req = db.get(m.EditRequest, p.edit_request_id)
        req.summary = ((req.summary or "") + f"\n[거절 사유] 제안 {p.id}: {reason.strip()[:300]}").strip()
    _close_if_decided(db, p.edit_request_id)
    db.commit()


def _close_if_decided(db: Session, edit_request_id: int) -> None:
    """요청의 제안을 모두 처리했으면 요청 상태를 done으로 바꾼다."""
    db.flush()
    pending = db.scalar(select(m.ChangeProposal.id).where(m.ChangeProposal.edit_request_id == edit_request_id,
                                                          m.ChangeProposal.status == "pending").limit(1))
    if pending is None:
        req = db.get(m.EditRequest, edit_request_id)
        if req.status == "proposed":
            req.status = "done"
