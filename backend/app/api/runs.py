# runs.py : 생성 실행 API(설계서 6절, 8절). 실행 시작(202), 진행 알림(SSE), 상태 조회, 구성안 조회.
import asyncio
import json
import queue

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from app.api import deps
from app.api.schemas import OutlineView, RunBrief, RunCreated
from app.api.views import outline_view
from app.db import models as m
from app.db import session as db_session
from app.db.session import get_db
from app.pipeline import runner
from app.pipeline.events import hub

router = APIRouter(tags=["생성 실행"])

# SSE 대기 간격. 큐가 비어 있으면 0.25초 쉬었다 다시 본다. 화면이 진행을 늦게 느끼지 않으면서 CPU를 쓰지 않는 값이다.
POLL_SEC = 0.25
# 이벤트를 놓쳤을 때를 대비해 이 간격(초)마다 DB의 실행 상태를 다시 본다. 끝났으면 완료 이벤트를 보내고 연결을 닫는다.
DB_RECHECK_SEC = 3.0
# 연결이 끊기지 않게 15초마다 빈 신호(ping)를 보낸다. 프록시나 브라우저가 조용한 연결을 끊는 일을 막는다.
PING_SEC = 15


@router.post("/api/projects/{project_id}/runs", response_model=RunCreated, status_code=202)
def create_run(project_id: int, db: Session = Depends(get_db)):
    """생성 실행을 시작한다. 실행 기록만 만들고 바로 202와 run_id를 돌려주며, 생성은 백그라운드 스레드에서 돈다."""
    try:
        run = runner.start_run(db, project_id)
    except runner.RunError as exc:
        raise HTTPException(exc.status_code, str(exc))
    runner.launch(run.id)
    return RunCreated(run_id=run.id)


@router.get("/api/runs/{run_id}", response_model=RunBrief)
def get_run(run_id: int, db: Session = Depends(get_db)):
    return deps.get_or_404(db, m.GenerationRun, run_id, "생성 실행")


@router.get("/api/runs/{run_id}/snapshot")
def get_run_snapshot(run_id: int, db: Session = Depends(get_db)):
    """SSE를 쓰지 못하는 환경을 위한 단계별 상태 조회. SSE가 처음 보내는 snapshot 이벤트와 같은 내용이다."""
    return runner.run_snapshot(db, deps.get_or_404(db, m.GenerationRun, run_id, "생성 실행"))


@router.get("/api/runs/{run_id}/events")
async def run_events(run_id: int, request: Request):
    """SSE로 단계 시작, 단계 완료, LLM 호출, 오류, 전체 완료 이벤트를 보낸다.
    연결하면 먼저 DB로 만든 snapshot을 보내고, 실행이 이미 끝났으면 done을 보내고 닫는다.
    요청 세션(Depends)을 쓰지 않는 이유: 스트림이 오래 열려 있는 동안 연결 풀의 연결 하나를 계속 붙잡지 않으려고,
    DB가 필요할 때만 짧게 세션을 열고 닫는다."""
    def load_snapshot():
        db = db_session.SessionLocal()
        try:
            run = db.get(m.GenerationRun, run_id)
            return runner.run_snapshot(db, run) if run else None
        finally:
            db.close()

    key = runner.run_key(run_id)
    q = hub.subscribe(key)   # snapshot을 읽기 전에 구독부터 해야, 그 사이에 난 이벤트를 놓치지 않는다
    snap = await asyncio.to_thread(load_snapshot)
    if snap is None:
        hub.unsubscribe(key, q)
        raise HTTPException(404, f"생성 실행을 찾을 수 없습니다 (id {run_id}).")

    async def stream():
        try:
            yield {"event": "snapshot", "data": json.dumps(snap, ensure_ascii=False, default=str)}
            if snap["status"] in ("done", "failed"):
                yield {"event": "done", "data": json.dumps({"type": "done", "run_id": run_id, "status": snap["status"],
                                                            "message": snap["error_message"]}, ensure_ascii=False)}
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
                    if waited >= DB_RECHECK_SEC:   # 이벤트 없이 오래 조용하면 DB로 끝났는지 확인한다
                        waited = 0.0
                        latest = await asyncio.to_thread(load_snapshot)
                        if latest and latest["status"] in ("done", "failed"):
                            yield {"event": "snapshot", "data": json.dumps(latest, ensure_ascii=False, default=str)}
                            yield {"event": "done", "data": json.dumps(
                                {"type": "done", "run_id": run_id, "status": latest["status"],
                                 "message": latest["error_message"]}, ensure_ascii=False)}
                            return
                    continue
                waited = 0.0
                yield {"event": ev["type"], "data": json.dumps(ev, ensure_ascii=False, default=str)}
                if ev["type"] == "done":
                    return
        finally:
            hub.unsubscribe(key, q)

    return EventSourceResponse(stream(), ping=PING_SEC)


@router.get("/api/projects/{project_id}/outline", response_model=OutlineView)
def get_outline(project_id: int, db: Session = Depends(get_db)):
    """현재 구성안과 장면 목록, 장면별 내레이션과 자막을 조회한다."""
    deps.project_or_404(db, project_id)
    outline = deps.current_outline(db, project_id)
    if outline is None:
        raise HTTPException(404, "아직 생성된 구성안이 없습니다.")
    return outline_view(db, outline)
