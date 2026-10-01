# manual.py : 맞춤 매뉴얼, 주의사항, 수행 일정 조회·수정 API(설계서 6절).
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import config
from app.api import deps
from app.api.schemas import ManualStepPatch, ManualView, ScheduleItemPatch
from app.api.views import manual_view
from app.db import models as m
from app.db.session import get_db
from app.pipeline import persist, review
from app.pipeline.schedule import layout

router = APIRouter(tags=["매뉴얼·일정"])

STEP_FIELDS = ("title", "instruction", "tip")


@router.get("/api/projects/{project_id}/manual", response_model=ManualView)
def get_manual(project_id: int, db: Session = Depends(get_db)):
    """현재 맞춤 매뉴얼, 주의사항, 수행 일정을 조회한다."""
    deps.project_or_404(db, project_id)
    manual = deps.current_manual(db, project_id)
    if manual is None:
        raise HTTPException(404, "아직 생성된 매뉴얼이 없습니다. 매뉴얼형이나 둘 다로 생성해 주세요.")
    return manual_view(db, manual)


@router.patch("/api/manual-steps/{step_id}", response_model=ManualView)
def patch_manual_step(step_id: int, body: ManualStepPatch, db: Session = Depends(get_db)):
    """매뉴얼 단계를 고친다. 바뀐 필드마다 revision을 남기고 edited_fields에 기록한다(설계서 10절 규칙 1).
    단계 제목이 바뀌면 그 단계를 수행하는 일정 항목의 제목도 함께 바꾼다(사용자가 일정 제목을 따로 고치지 않았을 때)."""
    step = deps.get_or_404(db, m.ManualStep, step_id, "매뉴얼 단계")
    changes = body.model_dump(exclude_unset=True)
    for field_name in STEP_FIELDS:
        if field_name not in changes:
            continue
        new = changes[field_name]
        new = new.strip() if isinstance(new, str) else new
        if field_name == "tip" and not new:
            new = None                          # 빈 팁은 "팁 없음"으로 저장한다
        old = getattr(step, field_name)
        if new == old:
            continue
        persist.add_revision(db, "manual_step", step.id, field_name, old, new, config.DEFAULT_USER_ID)
        persist.mark_edited(step, field_name)
        setattr(step, field_name, new)
        if field_name == "title":
            for it in step.manual.schedule:
                if it.manual_step_id == step.id and it.source == "ai" and it.title == old:
                    it.title = new[:200]
    db.commit()
    review.recheck_for_run_id(db, step.manual.run_id)   # 고친 문장의 수치(C08)와 표현(C12)을 다시 확인한다
    return manual_view(db, step.manual)


@router.patch("/api/schedule-items/{item_id}", response_model=ManualView)
def patch_schedule_item(item_id: int, body: ScheduleItemPatch, db: Session = Depends(get_db)):
    """일정 항목을 고친다. 기간을 바꾸면 그 뒤 항목들의 시작일(며칠째)을 코드가 다시 배치한다(결정 2, 검수 C09).
    사용자가 고친 항목은 source를 user로 바꿔 화면에서 구분할 수 있게 한다."""
    item = deps.get_or_404(db, m.ScheduleItem, item_id, "일정 항목")
    changes = body.model_dump(exclude_unset=True)
    if "interval_days" in changes and changes["interval_days"] == 0:
        changes["interval_days"] = None
    changed = False
    for field_name, new in changes.items():
        new = new.strip() if isinstance(new, str) else new
        old = getattr(item, field_name)
        if new == old:
            continue
        persist.add_revision(db, "schedule_item", item.id, field_name, old, new, config.DEFAULT_USER_ID)
        setattr(item, field_name, new)
        changed = True
    if changed:
        item.source = "user"
        relayout(item.manual)
    db.commit()
    if changed:
        review.recheck_for_run_id(db, item.manual.run_id)
    return manual_view(db, item.manual)


def relayout(manual: m.Manual) -> None:
    """일정 항목을 지금 순서(seq)대로 다시 이어 붙인다. 기간과 주기는 그대로 두고 시작일만 다시 계산한다."""
    items = sorted(manual.schedule, key=lambda it: it.seq)
    placed = layout([{"seq": it.seq, "title": it.title, "duration_days": it.duration_days,
                      "interval_days": it.interval_days} for it in items])
    for it, p in zip(items, placed):
        it.start_offset_day = p["start_offset_day"]
