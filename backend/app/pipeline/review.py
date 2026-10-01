# review.py : 6단계 검수의 DB 쪽 일(설계서 10절).
# checks.py의 순수 함수로 결과를 계산하고, 여기서는
#   1) DB에서 검수 입력을 모으고(build_input),
#   2) 코드로 고칠 수 있는 실패를 자동으로 고치고(C06·C07 자막 재분할, C09 일정 재배치, C10 주의사항 후보 추가),
#   3) 저장 정책을 적용해(다시 요청해도 실패한 항목은 경고로 남긴다) review_check에 저장한다.
# 생성 실행의 6단계(runner)와, 사용자가 결과를 고친 뒤의 다시 검수(API)가 같은 evaluate()를 쓴다.
from datetime import datetime
from typing import Optional

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db import models as m
from app.pipeline import checks, persist
from app.pipeline.budget import compute_budget
from app.pipeline.schedule import layout

# 검수 항목 이름(화면의 검수 패널과 결과보고서에 쓴다). 설계서 10절 표의 "검사 내용"을 짧게 줄였다.
CHECK_LABEL = {
    "C01": "스키마 통과", "C02": "장면 수 일치", "C03": "근거 문단 있음", "C04": "분량 예산 이내",
    "C05": "키워드 포함", "C06": "자막 줄 길이", "C07": "자막 시간", "C08": "수치 원고 일치",
    "C09": "일정 순서", "C10": "경고 문장 반영", "C11": "출력 언어", "C12": "과장 표현 없음",
    "H01": "원고 의도 반영", "H02": "대상 수준 적합", "H03": "제작 가능성",
}
HUMAN_CODES = ("H01", "H02", "H03")
# 실패해도 다시 요청하지 않고 처음부터 경고로만 표시하는 항목(설계서 10절 "실패했을 때" 칸).
WARN_ONLY = {"C05", "C10", "C12"}
# 코드가 자동으로 고치는 항목. 고친 뒤 다시 검사해 통과하면 "자동 수정"으로 표시한다.
AUTO_FIX = {"C06", "C07", "C09"}


# ---------- 1. 입력 모으기 ----------
def run_outline(db: Session, run_id: int) -> Optional[m.Outline]:
    return db.scalars(select(m.Outline).where(m.Outline.run_id == run_id).order_by(m.Outline.id.desc())).first()


def run_manual(db: Session, run_id: int) -> Optional[m.Manual]:
    return db.scalars(select(m.Manual).where(m.Manual.run_id == run_id).order_by(m.Manual.id.desc())).first()


def build_input(db: Session, run: m.GenerationRun) -> checks.CheckInput:
    """실행 하나의 결과를 checks.run_checks가 받는 모양으로 모은다.
    세션은 expire_on_commit=False라 앞에서 읽어 둔 관계 목록(outline.scenes 등)이 새로 더한 행을 모를 수 있다.
    검수는 언제나 DB의 최신 상태를 봐야 하므로, 아직 보내지 않은 변경을 먼저 flush한 뒤 읽어 둔 객체를 모두 만료시킨다."""
    db.flush()
    db.expire_all()
    setting = db.get(m.GenerationSetting, run.setting_id)
    source = db.get(m.SourceDocument, run.source_id)
    expected = compute_budget(setting.target_duration_sec, setting.scene_count,
                              setting.scene_default_sec, setting.narration_cpm).scene_count
    inp = checks.CheckInput(content_type=setting.content_type, language=setting.output_language,
                            keywords=list(setting.keywords or []), subtitle_max_chars=setting.subtitle_max_chars,
                            paragraphs=list(source.paragraphs or []), expected_scene_count=expected)
    outline = run_outline(db, run.id)
    if outline is not None:
        inp.outline = {"title": outline.title, "summary": outline.summary,
                       "learning_objectives": list(outline.learning_objectives or [])}
        scene_ids = [s.id for s in outline.scenes]
        scene_cautions: dict[int, list[str]] = {}
        if scene_ids:
            for c in db.scalars(select(m.Caution).where(m.Caution.scene_id.in_(scene_ids))):
                scene_cautions.setdefault(c.scene_id, []).append(c.body)
        for s in outline.scenes:
            narr = s.narration
            inp.scenes.append({
                "id": s.id, "seq": s.seq, "title": s.title, "key_point": s.key_point,
                "source_paragraphs": list(s.source_paragraphs or []), "screen_description": s.screen_description,
                "visual_suggestion": s.visual_suggestion, "on_screen_text": s.on_screen_text,
                "duration_sec": s.duration_sec, "char_budget": s.char_budget,
                "narration": {"id": narr.id, "body": narr.body} if narr else None,
                "cues": [{"seq": c.seq, "start_ms": c.start_ms, "end_ms": c.end_ms, "body": c.body}
                         for c in (narr.cues if narr else [])],
                "cautions": scene_cautions.get(s.id, [])})
    manual = run_manual(db, run.id)
    if manual is not None:
        step_seq = {st.id: st.seq for st in manual.steps}
        inp.manual = {
            "id": manual.id, "title": manual.title, "intro": manual.intro,
            "steps": [{"id": st.id, "seq": st.seq, "title": st.title, "instruction": st.instruction, "tip": st.tip,
                       "source_paragraphs": list(st.source_paragraphs or [])} for st in manual.steps],
            "cautions": [{"body": c.body} for c in manual.cautions],
            "schedule": [{"seq": it.seq, "step_seq": step_seq.get(it.manual_step_id, it.seq), "title": it.title,
                          "start_offset_day": it.start_offset_day, "duration_days": it.duration_days}
                         for it in manual.schedule]}
    return inp


# ---------- 2. 자동 수정 ----------
def apply_fixes(db: Session, run: m.GenerationRun, results: list[checks.CheckResult]) -> set[tuple[str, Optional[int]]]:
    """코드로 고칠 수 있는 실패를 고친다. 고친 (검사 코드, 대상 id) 목록을 돌려준다.
    - C06·C07: 그 내레이션의 자막을 subtitles.py로 다시 나누고 시간을 다시 계산한다.
    - C09: 일정을 매뉴얼 단계 순서대로 다시 배치한다.
    - C10: 빠진 경고 문장을 주의사항 후보(source='rule', 위험도 warning)로 더한다. 결과는 경고로 남아 사람이 확인한다."""
    fixed: set[tuple[str, Optional[int]]] = set()
    setting = db.get(m.GenerationSetting, run.setting_id)

    narr_ids = {r.target_ref for r in results if r.code in ("C06", "C07") and r.failed and r.target_ref}
    for nid in narr_ids:
        narr = db.get(m.Narration, nid)
        if narr is None:
            continue
        persist.resplit_cues(db, narr, narr.scene.duration_sec, setting.subtitle_max_chars)
        fixed.update({("C06", nid), ("C07", nid)})

    if any(r.code == "C09" and r.failed for r in results):
        manual = run_manual(db, run.id)
        if manual is not None:
            step_seq = {st.id: st.seq for st in manual.steps}
            items = sorted(manual.schedule, key=lambda it: step_seq.get(it.manual_step_id, it.seq))
            placed = layout([{"seq": i, "title": it.title, "duration_days": it.duration_days,
                              "interval_days": it.interval_days} for i, it in enumerate(items, 1)])
            for it, p in zip(items, placed):
                it.seq, it.start_offset_day, it.duration_days = p["seq"], p["start_offset_day"], p["duration_days"]
            fixed.add(("C09", manual.id))

    for r in results:
        if r.code != "C10" or not r.data.get("missing"):
            continue
        manual = run_manual(db, run.id)
        outline = run_outline(db, run.id)
        for w in r.data["missing"]:
            body = w["sentence"][:500]
            if manual is not None:
                db.add(m.Caution(manual_id=manual.id, severity="warning", body=body, source="rule"))
            elif outline is not None and outline.scenes:
                # 영상형만 있으면 그 문장을 근거로 쓴 장면에 붙이고, 그런 장면이 없으면 첫 장면에 붙인다.
                # caution은 manual_id와 scene_id 중 하나가 꼭 있어야 한다(schema.sql 머리말, 앱에서 검사).
                scene = next((s for s in outline.scenes if w["paragraph"] in (s.source_paragraphs or [])),
                             outline.scenes[0])
                db.add(m.Caution(scene_id=scene.id, severity="warning", body=body, source="rule"))
        fixed.add(("C10", None))
    db.flush()
    return fixed


# ---------- 3. 저장 정책 ----------
def final_result(r: checks.CheckResult, retried: bool, fixed: bool) -> tuple[str, str]:
    """저장할 (결과, 메시지). 설계서 10절: "다시 요청해도 실패한 자동 항목은 경고로 남기고 사람에게 넘긴다."
    C01(생성 자체 실패)만 fail로 남긴다. 다시 요청한 적이 있으면 메시지 앞에 그 사실을 적어 결과보고서에서 셀 수 있게 한다."""
    msg = r.message
    if r.code == "C01":
        return r.result, msg
    if r.result == checks.PASS:
        if fixed:
            return checks.PASS, "자동으로 고쳤습니다. " + msg
        if retried:
            return checks.PASS, "1회 다시 요청해 통과했습니다. " + msg
        return checks.PASS, msg
    if r.code == "C10" and fixed:
        return checks.WARN, msg + " 빠진 문장을 주의사항 후보로 추가했으니 확인해 주세요."
    if r.code in WARN_ONLY:
        return checks.WARN, msg
    if retried:
        return checks.WARN, "1회 다시 요청했지만 통과하지 못했습니다. " + msg
    return checks.WARN, "사람 확인이 필요합니다. " + msg


def evaluate(db: Session, run: m.GenerationRun, notes: Optional[list[checks.CheckResult]] = None,
             retried: Optional[set] = None, initial: bool = False) -> dict:
    """실행 하나를 검수하고 review_check에 저장한다.
    initial=True(생성 6단계)이면 C01을 포함해 자동 항목을 새로 쓰고, False(수정 뒤 다시 검수)이면 C01은 그대로 두고 C02~C12만 바꾼다.
    사람 확인 항목(H01~H03)은 없을 때만 'unchecked'로 만들고, 이미 있으면 건드리지 않는다."""
    notes = notes or []
    retried = retried or set()
    results = checks.run_checks(build_input(db, run))
    fixed = apply_fixes(db, run, results)
    if fixed - {("C10", None)}:
        # 자막·일정을 고쳤으면 그 결과로 다시 검사해 최종 상태를 저장한다(C10은 다시 검사하면 통과로 보여
        # "후보를 추가했다"는 경고가 사라지므로 처음 결과를 쓴다).
        again = {(r.code, r.target_ref): r for r in checks.run_checks(build_input(db, run))}
        results = [again.get((r.code, r.target_ref), r) if r.code in AUTO_FIX else r for r in results]

    rows: list[m.ReviewCheck] = []
    c01 = [n for n in notes if n.code == "C01"]
    if initial:
        rows += [m.ReviewCheck(run_id=run.id, check_code="C01", target_type=n.target_type, target_id=n.target_ref,
                               result=checks.FAIL, message=n.message[:500]) for n in c01]
        if not c01:
            rows.append(m.ReviewCheck(run_id=run.id, check_code="C01", target_type="run", target_id=run.id,
                                      result=checks.PASS, message="모든 LLM 단계의 출력이 JSON 스키마를 통과했습니다."))
    for r in results:
        is_fixed = (r.code, r.target_ref) in fixed or (r.code == "C10" and ("C10", None) in fixed)
        was_retried = (r.code, r.target_type, r.target_ref) in retried
        result, message = final_result(r, was_retried, is_fixed)
        rows.append(m.ReviewCheck(run_id=run.id, check_code=r.code, target_type=r.target_type,
                                  target_id=r.target_ref, result=result, message=message[:500]))

    codes = [f"C{i:02d}" for i in range(1 if initial else 2, 13)]
    db.execute(delete(m.ReviewCheck).where(m.ReviewCheck.run_id == run.id, m.ReviewCheck.check_code.in_(codes)))
    db.add_all(rows)
    ensure_human_rows(db, run.id)
    db.commit()
    return summarize(db, run.id)


def ensure_human_rows(db: Session, run_id: int) -> None:
    """사람 확인 항목 세 개를 '확인 전(unchecked)'으로 만들어 둔다. 검수 패널의 체크박스가 이 행을 쓴다."""
    have = set(db.scalars(select(m.ReviewCheck.check_code).where(m.ReviewCheck.run_id == run_id,
                                                                  m.ReviewCheck.check_code.in_(HUMAN_CODES))))
    for code in HUMAN_CODES:
        if code not in have:
            db.add(m.ReviewCheck(run_id=run_id, check_code=code, target_type="run", target_id=run_id,
                                 result="unchecked", message=CHECK_LABEL[code]))


def summarize(db: Session, run_id: int) -> dict:
    """자동 항목의 결과 수와 통과율. 통과율은 결과보고서의 품질 지표다(설계서 10절 머리말)."""
    rows = db.scalars(select(m.ReviewCheck.result).where(m.ReviewCheck.run_id == run_id,
                                                         m.ReviewCheck.check_code.like("C%"))).all()
    counts = {k: rows.count(k) for k in ("pass", "warn", "fail")}
    total = sum(counts.values())
    return {**counts, "total": total, "pass_rate": round(counts["pass"] / total, 3) if total else None}


def recheck_for_run_id(db: Session, run_id: int) -> dict:
    """사용자가 결과를 고친 뒤 부른다. 코드 검수만 다시 하며 LLM을 부르지 않는다."""
    run = db.get(m.GenerationRun, run_id)
    return evaluate(db, run, initial=False) if run else {}


def set_human_check(db: Session, run_id: int, code: str, checked: bool, user_id: int,
                    note: Optional[str] = None) -> m.ReviewCheck:
    """사람 확인 항목의 체크 여부와 확인자를 저장한다(설계서 10절 규칙 5)."""
    ensure_human_rows(db, run_id)
    db.flush()
    row = db.scalars(select(m.ReviewCheck).where(m.ReviewCheck.run_id == run_id,
                                                 m.ReviewCheck.check_code == code)).first()
    row.result = "pass" if checked else "unchecked"
    row.checked_by = user_id if checked else None
    row.checked_at = datetime.now() if checked else None
    row.message = (note.strip()[:500] if note and note.strip() else CHECK_LABEL[code])
    db.commit()
    return row
