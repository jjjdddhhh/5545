# checks.py : 검수 결과 조회와 사람 확인 저장 API(설계서 6절, 10절 규칙 5).
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import config
from app.api import deps
from app.api.schemas import CheckItem, ChecksView, HumanCheckIn
from app.db import models as m
from app.db.session import get_db
from app.pipeline import review

router = APIRouter(tags=["검수"])


def checks_view(db: Session, run_id: int) -> ChecksView:
    rows = db.scalars(select(m.ReviewCheck).where(m.ReviewCheck.run_id == run_id)
                      .order_by(m.ReviewCheck.check_code, m.ReviewCheck.id)).all()
    items = []
    for r in rows:
        it = CheckItem.model_validate(r)
        it.label = review.CHECK_LABEL.get(r.check_code, r.check_code)
        items.append(it)
    return ChecksView(run_id=run_id, summary=review.summarize(db, run_id),
                      auto=[i for i in items if i.check_code.startswith("C")],
                      human=[i for i in items if i.check_code.startswith("H")])


@router.get("/api/runs/{run_id}/checks", response_model=ChecksView)
def get_checks(run_id: int, db: Session = Depends(get_db)):
    """검수 결과를 항목별로 조회한다. 자동 항목(C01~C12)과 사람 확인 항목(H01~H03)을 나눠 돌려준다."""
    deps.get_or_404(db, m.GenerationRun, run_id, "생성 실행")
    review.ensure_human_rows(db, run_id)   # 검수 전에 끝난 실행(실패 등)에도 체크박스를 보여 줄 수 있게 한다
    db.commit()
    return checks_view(db, run_id)


@router.post("/api/runs/{run_id}/checks/recheck", response_model=ChecksView)
def recheck(run_id: int, db: Session = Depends(get_db)):
    """코드 검수(C02~C12)를 지금 결과로 다시 한다. LLM은 부르지 않는다. 표현 사전을 고친 뒤 결과를 다시 볼 때 쓴다."""
    run = deps.get_or_404(db, m.GenerationRun, run_id, "생성 실행")
    if run.status != "done":
        raise HTTPException(400, "끝난 실행만 다시 검수할 수 있습니다.")
    review.evaluate(db, run, initial=False)
    return checks_view(db, run_id)


@router.put("/api/runs/{run_id}/human-checks/{code}", response_model=ChecksView)
def put_human_check(run_id: int, code: str, body: HumanCheckIn, db: Session = Depends(get_db)):
    """사람 확인 항목(H01 원고 의도 반영, H02 대상 수준 적합, H03 제작 가능성)의 체크 여부와 확인자를 저장한다."""
    deps.get_or_404(db, m.GenerationRun, run_id, "생성 실행")
    code = code.upper()
    if code not in review.HUMAN_CODES:
        raise HTTPException(400, f"사람 확인 항목은 {', '.join(review.HUMAN_CODES)} 중 하나입니다.")
    review.set_human_check(db, run_id, code, body.checked, config.DEFAULT_USER_ID, body.note)
    return checks_view(db, run_id)
