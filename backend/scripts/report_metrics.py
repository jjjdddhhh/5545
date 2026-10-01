# report_metrics.py : 결과보고서용 지표를 DB에서 뽑는다(설계서 11절 8번).
# - 생성 시간: generation_run의 시작·끝 시각, agent_step_log의 단계별 걸린 시간과 토큰 수, 장면당 생성 시간
# - 검수 통과율: review_check의 자동 항목(C01~C12) 결과, 다시 요청한 항목 수, 사람 확인(H01~H03) 완료 수
# - 사용자 수정 횟수: revision을 프로젝트별, 대상 종류별로 센다
# - 수정 요청 에이전트: edit_request 상태별 수, 평균 도구 호출 수, 제안 승인율
# 실행 예(backend 폴더에서):
#   python scripts/report_metrics.py                       모든 프로젝트
#   python scripts/report_metrics.py --project-id 3 --out ../docs/eval/metrics.md
import argparse
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.db import models as m  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402

LLM_STAGES = ("chunk_summary", "outline", "scene_detail", "narration", "manual")


def run_metrics(db: Session, run: m.GenerationRun) -> dict:
    """실행 하나의 지표."""
    logs = db.scalars(select(m.AgentStepLog).where(m.AgentStepLog.run_id == run.id)).all()
    llm = [lg for lg in logs if lg.stage in LLM_STAGES]
    stage_ms: dict[str, int] = defaultdict(int)
    for lg in logs:
        stage_ms[lg.stage] += lg.latency_ms or 0
    outline = db.scalars(select(m.Outline).where(m.Outline.run_id == run.id)).first()
    scenes = len(outline.scenes) if outline else 0
    checks = db.scalars(select(m.ReviewCheck).where(m.ReviewCheck.run_id == run.id)).all()
    auto = [c for c in checks if c.check_code.startswith("C")]
    human = [c for c in checks if c.check_code.startswith("H")]
    seconds = (run.finished_at - run.started_at).total_seconds() if run.finished_at and run.started_at else None
    return {
        "run_id": run.id, "model": run.llm_model, "status": run.status, "seconds": seconds, "scenes": scenes,
        "llm_calls": sum(1 for lg in llm if lg.status in ("ok", "failed")),
        "format_retries": sum(1 for lg in llm if lg.status == "retry"),
        "check_retries": sum(1 for c in auto if (c.message or "").startswith("1회 다시 요청")),
        "tokens_in": sum(lg.tokens_in or 0 for lg in llm), "tokens_out": sum(lg.tokens_out or 0 for lg in llm),
        "truncation": sum(1 for lg in llm if isinstance(lg.output_json, dict) and lg.output_json.get("truncation_risk")),
        "per_scene_sec": ((stage_ms["scene_detail"] + stage_ms["narration"]) / 1000 / scenes) if scenes else None,
        "stage_sec": {k: round(v / 1000, 1) for k, v in stage_ms.items()},
        "auto_total": len(auto), "auto_pass": sum(c.result == "pass" for c in auto),
        "auto_warn": sum(c.result == "warn" for c in auto), "auto_fail": sum(c.result == "fail" for c in auto),
        "by_code": Counter(c.check_code for c in auto if c.result != "pass"),
        "human_done": sum(c.result == "pass" for c in human),
    }


def revision_counts(db: Session, project_id: int) -> Counter:
    """프로젝트의 사용자 수정 횟수를 대상 종류별로 센다. revision은 entity_type과 entity_id만 가지므로
    프로젝트에 속한 장면, 내레이션, 매뉴얼 단계, 일정 id를 먼저 모은 뒤 대조한다."""
    outlines = db.scalars(select(m.Outline.id).where(m.Outline.project_id == project_id)).all()
    manuals = db.scalars(select(m.Manual.id).where(m.Manual.project_id == project_id)).all()
    scene_ids = set(db.scalars(select(m.Scene.id).where(m.Scene.outline_id.in_(outlines)))) if outlines else set()
    narr_ids = set(db.scalars(select(m.Narration.id).where(m.Narration.scene_id.in_(scene_ids)))) if scene_ids else set()
    step_ids = set(db.scalars(select(m.ManualStep.id).where(m.ManualStep.manual_id.in_(manuals)))) if manuals else set()
    item_ids = set(db.scalars(select(m.ScheduleItem.id).where(m.ScheduleItem.manual_id.in_(manuals)))) if manuals else set()
    owned = {"scene": scene_ids, "narration": narr_ids, "manual_step": step_ids, "schedule_item": item_ids}
    counts: Counter = Counter()
    for etype, eid in db.execute(select(m.Revision.entity_type, m.Revision.entity_id)):
        if eid in owned.get(etype, set()):
            counts[etype] += 1
    return counts


def edit_metrics(db: Session, project_id: int) -> dict:
    reqs = db.scalars(select(m.EditRequest).where(m.EditRequest.project_id == project_id)).all()
    ids = [r.id for r in reqs]
    props = db.scalars(select(m.ChangeProposal).where(m.ChangeProposal.edit_request_id.in_(ids))).all() if ids else []
    decided = [p for p in props if p.status != "pending"]
    return {"requests": len(reqs), "by_status": Counter(r.status for r in reqs),
            "avg_tool_calls": (sum(r.tool_calls for r in reqs) / len(reqs)) if reqs else None,
            "proposals": len(props), "accepted": sum(p.status == "accepted" for p in props),
            "rejected": sum(p.status == "rejected" for p in props),
            "accept_rate": (sum(p.status == "accepted" for p in decided) / len(decided)) if decided else None}


def render(db: Session, project_id: int | None) -> str:
    stmt = select(m.Project).order_by(m.Project.id)
    if project_id:
        stmt = stmt.where(m.Project.id == project_id)
    fmt = lambda v, d=1: "-" if v is None else (f"{v:.{d}f}" if isinstance(v, float) else str(v))
    pct = lambda a, b: "-" if not b else f"{a / b * 100:.0f}%"
    lines = ["# 결과보고서 지표", ""]
    for p in db.scalars(stmt):
        runs = db.scalars(select(m.GenerationRun).where(m.GenerationRun.project_id == p.id)
                          .order_by(m.GenerationRun.id)).all()
        lines += [f"## 프로젝트 {p.id} · {p.title}", "", "### 생성 실행", "",
                  "| 실행 | 모델 | 상태 | 생성 시간(초) | 장면 | 장면당(초) | LLM 호출 | 형식 재요청 | 검수 재요청 | 입력 토큰 | 출력 토큰 | 잘림 위험 | 자동 검수 통과율 | 경고 | 실패 | 사람 확인 |",
                  "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
        for r in runs:
            x = run_metrics(db, r)
            lines.append(f"| {x['run_id']} | {x['model']} | {x['status']} | {fmt(x['seconds'])} | {x['scenes']} | "
                         f"{fmt(x['per_scene_sec'])} | {x['llm_calls']} | {x['format_retries']} | {x['check_retries']} | "
                         f"{x['tokens_in']} | {x['tokens_out']} | {x['truncation']} | {pct(x['auto_pass'], x['auto_total'])} | "
                         f"{x['auto_warn']} | {x['auto_fail']} | {x['human_done']}/3 |")
        if runs:
            last = run_metrics(db, runs[-1])
            if last["by_code"]:
                lines += ["", "최근 실행에서 통과하지 못한 검수 항목: " +
                          ", ".join(f"{k} {v}건" for k, v in sorted(last["by_code"].items()))]
        rev = revision_counts(db, p.id)
        label = {"scene": "장면", "narration": "내레이션", "manual_step": "매뉴얼 단계", "schedule_item": "일정"}
        lines += ["", "### 사용자 수정 횟수", "", f"전체 {sum(rev.values())}회"
                  + ("" if not rev else " (" + ", ".join(f"{label.get(k, k)} {v}회" for k, v in rev.items()) + ")")]
        e = edit_metrics(db, p.id)
        accept = "-" if e["accept_rate"] is None else f"{e['accept_rate'] * 100:.0f}%"
        lines += ["", "### 수정 요청 에이전트", "",
                  f"요청 {e['requests']}건(" + (", ".join(f"{k} {v}" for k, v in e["by_status"].items()) or "없음") + "), "
                  f"평균 도구 호출 {fmt(e['avg_tool_calls'])}회, 제안 {e['proposals']}개 중 승인 {e['accepted']}개, "
                  f"거절 {e['rejected']}개, 승인율 {accept}", ""]
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="결과보고서용 지표를 DB에서 뽑아 Markdown으로 출력한다.")
    ap.add_argument("--project-id", type=int, default=None)
    ap.add_argument("--out", default=None, help="저장할 Markdown 파일 경로. 없으면 화면에만 출력한다")
    args = ap.parse_args()
    db = SessionLocal()
    try:
        text = render(db, args.project_id)
    finally:
        db.close()
    print(text)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"저장했습니다: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
