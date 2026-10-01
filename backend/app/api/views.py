# views.py : DB 행을 화면용 응답으로 모으는 함수. 구성안 조회, JSON 내보내기, 수정 요청 에이전트가 함께 쓴다.
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas import CueOut, ManualView, NarrationOut, OutlineInfo, OutlineView, SceneOut
from app.db import models as m

# 검수 결과의 나쁜 정도. 장면의 점 색은 그 장면에 걸린 결과 가운데 가장 나쁜 것을 쓴다.
SEVERITY = {"none": 0, "pass": 1, "unchecked": 1, "warn": 2, "fail": 3}


def worst(results: list[str]) -> str:
    """결과 목록에서 가장 나쁜 것을 고른다. 결과가 하나도 없으면 "none"(아직 검수 전)."""
    return max(results, key=lambda r: SEVERITY.get(r, 0), default="none")


def scene_check_status(db: Session, run_id: int, scenes: list[m.Scene]) -> dict[int, str]:
    """장면 id마다 자동 검수(C로 시작하는 코드)의 가장 나쁜 결과.
    장면에 직접 걸린 결과와 그 장면의 내레이션·자막에 걸린 결과를 모두 장면의 결과로 본다."""
    narr_to_scene = {sc.narration.id: sc.id for sc in scenes if sc.narration is not None}
    rows = db.execute(select(m.ReviewCheck.target_type, m.ReviewCheck.target_id, m.ReviewCheck.result)
                      .where(m.ReviewCheck.run_id == run_id, m.ReviewCheck.check_code.like("C%"))).all()
    found: dict[int, list[str]] = {sc.id: [] for sc in scenes}
    for ttype, tid, result in rows:
        if ttype == "scene" and tid in found:
            found[tid].append(result)
        elif ttype in ("narration", "subtitle") and tid in narr_to_scene:
            found[narr_to_scene[tid]].append(result)
    return {sid: worst(rs) for sid, rs in found.items()}


def scene_out(sc: m.Scene, start_sec: int = 0, check_status: str = "none") -> SceneOut:
    out = SceneOut.model_validate(sc)
    out.edited_fields = list(sc.edited_fields or [])
    out.start_sec = start_sec
    out.check_status = check_status
    if sc.narration is not None:
        out.narration = NarrationOut.model_validate(sc.narration)
        out.cues = [CueOut.model_validate(c) for c in sc.narration.cues]
    return out


def outline_view(db: Session, outline: m.Outline) -> OutlineView:
    """구성안 하나와 장면 목록(장면별 내레이션, 자막, 검수 상태 포함)."""
    scenes = list(outline.scenes)          # relationship이 seq 순서로 정렬해 준다
    status = scene_check_status(db, outline.run_id, scenes)
    out, start = [], 0
    for sc in scenes:
        out.append(scene_out(sc, start, status.get(sc.id, "none")))
        start += sc.duration_sec
    return OutlineView(outline=OutlineInfo.model_validate(outline), scenes=out, total_sec=start)


def step_check_status(db: Session, run_id: int, steps: list[m.ManualStep]) -> dict[int, str]:
    rows = db.execute(select(m.ReviewCheck.target_id, m.ReviewCheck.result)
                      .where(m.ReviewCheck.run_id == run_id, m.ReviewCheck.check_code.like("C%"),
                             m.ReviewCheck.target_type == "manual_step")).all()
    found: dict[int, list[str]] = {st.id: [] for st in steps}
    for tid, result in rows:
        if tid in found:
            found[tid].append(result)
    return {sid: worst(rs) for sid, rs in found.items()}


def manual_view(db: Session, manual: m.Manual) -> ManualView:
    from app.api.schemas import CautionOut, ManualInfo, ManualStepOut, ScheduleItemOut
    steps = list(manual.steps)
    status = step_check_status(db, manual.run_id, steps)
    step_out = []
    for st in steps:
        o = ManualStepOut.model_validate(st)
        o.edited_fields = list(st.edited_fields or [])
        o.check_status = status.get(st.id, "none")
        step_out.append(o)
    schedule = [ScheduleItemOut.model_validate(it) for it in manual.schedule]
    total = max((it.start_offset_day + it.duration_days for it in manual.schedule), default=0)
    return ManualView(manual=ManualInfo.model_validate(manual), steps=step_out,
                      cautions=[CautionOut.model_validate(c) for c in manual.cautions],
                      schedule=schedule, total_days=total)
