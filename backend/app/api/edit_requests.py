# edit_requests.py : 수정 요청 에이전트 API 다섯 개(설계서 6절, 13절).
#   POST /api/projects/{id}/edit-requests   수정 요청 접수(202)
#   GET  /api/edit-requests/{id}/events     에이전트가 부르는 도구와 결과를 SSE로
#   GET  /api/edit-requests/{id}/proposals  변경 제안을 바뀌기 전과 후로
#   POST /api/proposals/{id}/accept         제안 반영(revision, 내레이션이면 자막 재분할)
#   POST /api/proposals/{id}/reject         제안 거절(원래 내용 유지)
# 그 밖에 요청 상태 조회(GET /api/edit-requests/{id})와 프로젝트의 요청 목록(GET /api/projects/{id}/edit-requests)을 더했다.
import asyncio
import json
import queue
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from app import config
from app.agent import service
from app.agent.repo import SqlRepo, check_proposal
from app.api import deps
from app.api.schemas import (AgentActionOut, EditRequestCreated, EditRequestIn, EditRequestOut, ProposalOut,
                             RejectIn)
from app.db import models as m
from app.db import session as db_session
from app.db.session import get_db
from app.pipeline.events import hub
from app.pipeline.persist import setting_of_scene
from app.pipeline.subtitles import split_subtitles

router = APIRouter(tags=["수정 요청 에이전트"])

POLL_SEC = 0.25        # runs.py의 SSE와 같은 값과 같은 이유다
DB_RECHECK_SEC = 3.0
PING_SEC = 15
FINISHED = ("proposed", "refused", "limit", "failed", "done")


def request_out(db: Session, req: m.EditRequest) -> EditRequestOut:
    out = EditRequestOut.model_validate(req)
    actions = db.scalars(select(m.AgentAction).where(m.AgentAction.edit_request_id == req.id)
                         .order_by(m.AgentAction.seq, m.AgentAction.id)).all()
    out.actions = []
    for a in actions:
        ao = AgentActionOut.model_validate(a)
        ao.label = service.TOOL_LABEL.get(a.tool_name, a.tool_name)
        out.actions.append(ao)
    return out


@router.post("/api/projects/{project_id}/edit-requests", response_model=EditRequestCreated, status_code=202)
def create_edit_request(project_id: int, body: EditRequestIn, db: Session = Depends(get_db)):
    """자연어 수정 요청을 받아 에이전트를 백그라운드에서 실행하고 요청 id를 바로 돌려준다."""
    try:
        req = service.start_edit_request(db, project_id, body.request_text.strip())
    except service.EditRequestError as exc:
        raise HTTPException(exc.status_code, str(exc))
    service.launch(req.id)
    return EditRequestCreated(edit_request_id=req.id)


@router.get("/api/projects/{project_id}/edit-requests", response_model=list[EditRequestOut])
def list_edit_requests(project_id: int, db: Session = Depends(get_db)):
    """프로젝트의 수정 요청 이력(최근 것부터 20개). 화면을 다시 열었을 때 처리 중이던 요청을 이어서 보여 주는 데 쓴다."""
    deps.project_or_404(db, project_id)
    reqs = db.scalars(select(m.EditRequest).where(m.EditRequest.project_id == project_id)
                      .order_by(m.EditRequest.id.desc()).limit(20)).all()
    return [request_out(db, r) for r in reqs]


@router.get("/api/edit-requests/{edit_request_id}", response_model=EditRequestOut)
def get_edit_request(edit_request_id: int, db: Session = Depends(get_db)):
    return request_out(db, deps.get_or_404(db, m.EditRequest, edit_request_id, "수정 요청"))


@router.get("/api/edit-requests/{edit_request_id}/events")
async def edit_events(edit_request_id: int, request: Request):
    """SSE로 에이전트가 부르는 도구와 결과 요약을 차례로 보낸다.
    연결하면 먼저 DB에 저장된 지금까지의 상태(snapshot: 요청과 도구 호출 목록)를 보내고, 끝난 요청이면 done을 보내고 닫는다."""
    def load():
        db = db_session.SessionLocal()
        try:
            req = db.get(m.EditRequest, edit_request_id)
            return request_out(db, req).model_dump(mode="json") if req else None
        finally:
            db.close()

    key = service.edit_key(edit_request_id)
    q = hub.subscribe(key)        # 상태를 읽기 전에 구독부터 해 그 사이의 이벤트를 놓치지 않는다
    snap = await asyncio.to_thread(load)
    if snap is None:
        hub.unsubscribe(key, q)
        raise HTTPException(404, f"수정 요청을 찾을 수 없습니다 (id {edit_request_id}).")

    def done_event(s: dict) -> dict:
        return {"event": "done", "data": json.dumps({"type": "done", "status": s["status"], "summary": s["summary"]},
                                                    ensure_ascii=False)}

    async def stream():
        try:
            yield {"event": "snapshot", "data": json.dumps({"type": "snapshot", **snap}, ensure_ascii=False)}
            if snap["status"] in FINISHED:
                yield done_event(snap)
                return
            waited = 0.0
            while True:
                if await request.is_disconnected():
                    return
                try:
                    ev = q.get_nowait()
                except queue.Empty:
                    await asyncio.sleep(POLL_SEC)
                    waited += POLL_SEC
                    if waited >= DB_RECHECK_SEC:
                        waited = 0.0
                        latest = await asyncio.to_thread(load)
                        if latest and latest["status"] in FINISHED:
                            yield {"event": "snapshot", "data": json.dumps({"type": "snapshot", **latest},
                                                                           ensure_ascii=False)}
                            yield done_event(latest)
                            return
                    continue
                waited = 0.0
                yield {"event": ev["type"], "data": json.dumps(ev, ensure_ascii=False, default=str)}
                if ev["type"] == "done":
                    return
        finally:
            hub.unsubscribe(key, q)

    return EventSourceResponse(stream(), ping=PING_SEC)


def proposal_out(db: Session, p: m.ChangeProposal, repo: Optional[SqlRepo] = None) -> ProposalOut:
    """제안 하나를 화면용으로 만든다. 대상 이름, 지금 값과 stale 여부, 자막 미리보기, 제안 검수 결과를 채운다."""
    out = ProposalOut.model_validate(p)
    out.field_label = service.FIELD_LABEL.get(p.field_name, p.field_name)
    out.current_value = service.current_value(db, p)
    out.stale = p.status == "pending" and (out.current_value or "") != (p.before_value or "")
    scene: Optional[m.Scene] = None
    if p.target_type == "scene":
        scene = db.get(m.Scene, p.target_id)
    elif p.target_type == "narration":
        narr = db.get(m.Narration, p.target_id)
        scene = narr.scene if narr else None
    if scene is not None:
        out.scene_id = scene.id
        out.target_label = f"장면 {scene.seq} · {scene.title}"
    elif p.target_type == "manual_step":
        st = db.get(m.ManualStep, p.target_id)
        out.target_label = f"매뉴얼 {st.seq}단계 · {st.title}" if st else "매뉴얼 단계"
    if p.target_type == "narration":
        setting = setting_of_scene(db, scene) if scene is not None else None
        out.subtitle_preview = split_subtitles(p.after_value, setting.subtitle_max_chars if setting else
                                               config.SUBTITLE_MAX_CHARS)
    if repo is not None and p.status == "pending":
        try:
            # check_proposal은 edit_agent의 제안 모양(내레이션이면 target_id가 장면 id)을 받는다.
            target_id = scene.id if (p.target_type == "narration" and scene is not None) else p.target_id
            out.checks = check_proposal(repo, {"target_type": p.target_type, "target_id": target_id,
                                               "field_name": p.field_name, "after_value": p.after_value})
        except KeyError:
            out.checks = {"ok": False, "results": [{"code": "-", "result": "warn",
                                                    "message": "대상이 현재 결과에 없어 검수하지 못했습니다(다시 생성한 뒤의 예전 제안)."}]}
    return out


@router.get("/api/edit-requests/{edit_request_id}/proposals", response_model=list[ProposalOut])
def get_proposals(edit_request_id: int, db: Session = Depends(get_db)):
    """에이전트가 만든 변경 제안을 바뀌기 전과 후로 돌려준다."""
    req = deps.get_or_404(db, m.EditRequest, edit_request_id, "수정 요청")
    rows = db.scalars(select(m.ChangeProposal).where(m.ChangeProposal.edit_request_id == req.id)
                      .order_by(m.ChangeProposal.id)).all()
    repo = SqlRepo(db, req.project_id)
    return [proposal_out(db, p, repo) for p in rows]


@router.post("/api/proposals/{proposal_id}/accept", response_model=ProposalOut)
def accept_proposal(proposal_id: int, db: Session = Depends(get_db)):
    """제안을 반영하고 수정 이력을 남긴다. 내레이션 제안이면 자막을 코드로 다시 나눈다."""
    p = deps.get_or_404(db, m.ChangeProposal, proposal_id, "변경 제안")
    try:
        service.apply_proposal(db, p, config.DEFAULT_USER_ID)
    except service.EditRequestError as exc:
        raise HTTPException(exc.status_code, str(exc))
    db.refresh(p)
    return proposal_out(db, p)


@router.post("/api/proposals/{proposal_id}/reject", response_model=ProposalOut)
def reject_proposal(proposal_id: int, body: RejectIn = RejectIn(), db: Session = Depends(get_db)):
    """제안을 거절하고 원래 내용을 유지한다."""
    p = deps.get_or_404(db, m.ChangeProposal, proposal_id, "변경 제안")
    try:
        service.reject_proposal(db, p, config.DEFAULT_USER_ID, body.reason)
    except service.EditRequestError as exc:
        raise HTTPException(exc.status_code, str(exc))
    db.refresh(p)
    return proposal_out(db, p)
