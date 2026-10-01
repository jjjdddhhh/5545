# smoke_ollama.py : 실제 Ollama 모델로 구성안부터 매뉴얼까지 한 번 생성해 보는 확인 스크립트(설계서 11절 1번, 14절 C2).
# DB를 쓰지 않고 파이프라인 함수를 메모리에서 차례로 부른다. 단계마다 JSON 성공 여부, 재요청 횟수, 걸린 시간,
# 토큰 수, 잘림 위험을 표로 출력하고, 끝에 코드 검수(C02~C12) 결과를 보여 준다.
# 두 모델을 비교할 때는 --model만 바꿔 두 번 실행한다(테스트에서는 이 스크립트를 실제 모델로 돌리지 않는다).
#
# 실행 예(backend 폴더에서, Ollama가 켜져 있고 모델을 받아 둔 상태):
#   python scripts/smoke_ollama.py --model qwen3:8b
#   python scripts/smoke_ollama.py --model exaone3.5:7.8b --save ../docs/eval/smoke_exaone.json
import argparse
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # scripts 폴더에서 실행해도 app 패키지를 찾게 한다

from app import config  # noqa: E402
from app.llm import llm_client  # noqa: E402
from app.llm.prompt_store import file_prompt  # noqa: E402
from app.pipeline import budget as budget_mod  # noqa: E402
from app.pipeline import checks, text_cleaner  # noqa: E402
from app.pipeline.llm_step import ListRecorder  # noqa: E402
from app.pipeline.manual import generate_manual, outline_text  # noqa: E402
from app.pipeline.narration import NarrationInput, generate_narration  # noqa: E402
from app.pipeline.outline import generate_outline  # noqa: E402
from app.pipeline.scene_detail import SceneInput, generate_scene_detail  # noqa: E402
from app.pipeline.schedule import layout  # noqa: E402
from app.pipeline.subtitles import build_cues  # noqa: E402

DEFAULT_SOURCE = config.REPO_ROOT / "docs" / "eval" / "sample_drill.txt"
# 생각 모드(think)가 없는 모델. 이 모델에 think=False를 보내면 Ollama가 오류를 낼 수 있어 None으로 보낸다
# (llm_client.THINK 주석 참고). 모델 이름이 이 글자로 시작하면 자동으로 끈다.
NO_THINK_PREFIXES = ("exaone", "llama", "gemma", "mistral")
STAGE_LABEL = {"chunk_summary": "긴 원고 요약", "outline": "구조화·구성안", "scene_detail": "장면 상세",
               "narration": "내레이션", "manual": "맞춤 매뉴얼"}


def run_smoke(source_text: str, content_type: str = "both", duration: int = 150, audience: str = "신입 사원",
              difficulty: str = "beginner", keywords: list[str] | None = None, prompt=file_prompt) -> dict:
    """파이프라인을 한 번 돌리고 결과와 통계를 돌려준다. 단계 하나가 실패해도 가능한 데까지 진행한다.
    prompt는 단계 이름을 받아 PromptSet을 돌려주는 함수다(기본은 llm/prompts의 버전 1 파일)."""
    setting = SimpleNamespace(content_type=content_type, audience=audience, difficulty=difficulty,
                              output_language="ko", tone=None, keywords=keywords or ["보호장갑"],
                              narration_cpm=config.NARRATION_CPM, scene_default_sec=config.SCENE_DEFAULT_SEC,
                              subtitle_max_chars=config.SUBTITLE_MAX_CHARS)
    rec = ListRecorder()
    clean = text_cleaner.clean_pasted(source_text)
    paras = clean.paragraphs
    by_id = {p["id"]: p for p in paras}
    budget = budget_mod.compute_budget(duration, None, setting.scene_default_sec, setting.narration_cpm)
    stage_time: dict[str, float] = {}
    check_retries: dict[str, int] = {}
    errors: list[str] = []
    result: dict = {"paragraphs": len(paras), "budget": budget.as_dict(), "scenes": [], "manual": None}

    def timed(stage: str, fn):
        t0 = time.perf_counter()
        try:
            return fn()
        except llm_client.GenerationError as exc:
            errors.append(f"{STAGE_LABEL.get(stage, stage)}: {exc}")
            return None
        finally:
            stage_time[stage] = stage_time.get(stage, 0.0) + time.perf_counter() - t0

    o = timed("outline", lambda: generate_outline(rec, prompt("outline"), setting, paras, budget.scene_count))
    if o is None:
        return {**result, "rows": rec.rows, "stage_time": stage_time, "check_retries": check_retries, "errors": errors}
    check_retries["outline"] = int(o.retried)
    out = o.outline
    if len(out.scenes) != budget.scene_count:
        budget = budget_mod.compute_budget(budget.total_sec, len(out.scenes), setting.scene_default_sec,
                                           setting.narration_cpm)
    result["outline"] = {"title": out.title, "summary": out.summary, "learning_objectives": out.learning_objectives}

    for sc, dur, cb in zip(out.scenes, budget.durations, budget.char_budgets):
        row = {"id": sc.seq, "seq": sc.seq, "title": sc.title, "key_point": sc.key_point,
               "source_paragraphs": sc.source_paragraphs, "duration_sec": dur, "char_budget": cb,
               "screen_description": None, "visual_suggestion": None, "on_screen_text": None,
               "narration": None, "cues": [], "cautions": []}
        d = timed("scene_detail", lambda: generate_scene_detail(
            rec, prompt("scene_detail"), setting, out.title,
            SceneInput(sc.seq, sc.title, sc.key_point, dur, sc.source_paragraphs), by_id))
        if d is not None:
            check_retries["scene_detail"] = check_retries.get("scene_detail", 0) + int(d.retried)
            row.update(d.detail.model_dump())
        if content_type in ("video", "both"):
            n = timed("narration", lambda: generate_narration(
                rec, prompt("narration"), setting,
                NarrationInput(sc.seq, sc.title, sc.key_point, row["screen_description"], row["on_screen_text"],
                               dur, cb, sc.source_paragraphs), by_id))
            if n is not None:
                check_retries["narration"] = check_retries.get("narration", 0) + int(n.retried)
                row["narration"] = {"id": sc.seq, "body": n.text}
                row["cues"] = build_cues(n.text, dur, setting.subtitle_max_chars)
        result["scenes"].append(row)

    if content_type in ("manual", "both"):
        summary = outline_text(out.title, out.summary, out.learning_objectives,
                               [(s.seq, s.title, s.key_point) for s in out.scenes])
        mres = timed("manual", lambda: generate_manual(rec, prompt("manual"), setting, summary, paras))
        if mres is not None:
            check_retries["manual"] = int(mres.retried)
            mo = mres.manual
            result["manual"] = {
                "id": 1, "title": mo.title, "intro": mo.intro,
                "steps": [{"id": st.seq, "seq": st.seq, "title": st.title, "instruction": st.instruction,
                           "tip": st.tip, "source_paragraphs": st.source_paragraphs} for st in mo.steps],
                "cautions": [{"body": c.body, "severity": c.severity} for c in mo.cautions],
                "schedule": [{**it, "step_seq": it["step_seq"]} for it in layout(
                    [{"seq": st.seq, "title": st.title, "duration_days": st.duration_days,
                      "interval_days": st.interval_days} for st in mo.steps])]}

    inp = checks.CheckInput(content_type=content_type, language="ko", keywords=setting.keywords,
                            subtitle_max_chars=setting.subtitle_max_chars, paragraphs=paras,
                            expected_scene_count=budget_mod.compute_budget(duration, None).scene_count,
                            outline=result["outline"], scenes=result["scenes"], manual=result["manual"])
    result["checks"] = [{"code": r.code, "result": r.result, "target": r.target_type, "ref": r.target_ref,
                         "message": r.message} for r in checks.run_checks(inp)]
    return {**result, "rows": rec.rows, "stage_time": stage_time, "check_retries": check_retries, "errors": errors}


def stage_table(res: dict) -> list[dict]:
    """단계별 통계 표의 행. JSON 성공은 "형식 재요청 뒤 최종 성공한 호출 수 / 전체 호출 수"다."""
    rows = []
    for stage in ("chunk_summary", "outline", "scene_detail", "narration", "manual"):
        logs = [r for r in res["rows"] if r["stage"] == stage]
        if not logs and stage not in res["stage_time"]:
            continue
        final = [r for r in logs if r["status"] in ("ok", "failed")]   # 호출 하나의 마지막 시도
        rows.append({"stage": STAGE_LABEL[stage], "calls": len(final),
                     "json_ok": sum(r["status"] == "ok" for r in final),
                     "format_retry": sum(r["status"] == "retry" for r in logs),
                     "check_retry": res["check_retries"].get(stage, 0),
                     "seconds": round(res["stage_time"].get(stage, 0.0), 1),
                     "tokens_in": sum(r.get("tokens_in") or 0 for r in logs),
                     "tokens_out": sum(r.get("tokens_out") or 0 for r in logs),
                     "max_tokens_in": max((r.get("tokens_in") or 0 for r in logs), default=0),
                     "truncation": any(r.get("truncation_risk") for r in logs)})
    return rows


def print_report(model: str, res: dict) -> None:
    rows = stage_table(res)
    print(f"\n모델: {model}   num_ctx: {llm_client.NUM_CTX}   원고 문단: {res['paragraphs']}개   "
          f"장면 수(계산): {res['budget']['scene_count']}개")
    header = ["단계", "호출", "JSON 성공", "형식 재요청", "검수 재요청", "시간(초)", "입력 토큰", "출력 토큰", "최대 입력", "잘림 위험"]
    print("| " + " | ".join(header) + " |")
    print("|" + "---|" * len(header))
    for r in rows:
        print(f"| {r['stage']} | {r['calls']} | {r['json_ok']}/{r['calls']} | {r['format_retry']} | {r['check_retry']} | "
              f"{r['seconds']} | {r['tokens_in']} | {r['tokens_out']} | {r['max_tokens_in']} | "
              f"{'있음' if r['truncation'] else '없음'} |")
    n = max(len(res["scenes"]), 1)
    per_scene = (res["stage_time"].get("scene_detail", 0) + res["stage_time"].get("narration", 0)) / n
    total = sum(res["stage_time"].values())
    print(f"\n전체 생성 시간: {total:.1f}초, 장면당 생성 시간(장면 상세+내레이션): {per_scene:.1f}초")
    bad = [c for c in res.get("checks", []) if c["result"] != "pass"]
    passed = len(res.get("checks", [])) - len(bad)
    print(f"코드 검수: {passed}/{len(res.get('checks', []))} 통과")
    for c in bad:
        print(f"  - {c['code']} {c['result']} ({c['target']} {c['ref']}): {c['message']}")
    for e in res["errors"]:
        print(f"  ! 생성 실패: {e}")


def main() -> int:
    ap = argparse.ArgumentParser(description="실제 Ollama 모델로 샘플 원고를 한 번 생성해 단계별 통계를 출력한다.")
    ap.add_argument("--model", default=llm_client.MODEL, help="Ollama 모델 이름 (예: qwen3:8b, exaone3.5:7.8b)")
    ap.add_argument("--source", default=str(DEFAULT_SOURCE), help="원고 파일 경로(txt, docx, pdf, hwpx)")
    ap.add_argument("--content-type", default="both", choices=["video", "manual", "both"])
    ap.add_argument("--duration", type=int, default=150, help="목표 분량(초). 기본 150초(장면 5개)")
    ap.add_argument("--num-ctx", type=int, default=None, help="컨텍스트 길이. 없으면 .env의 OLLAMA_NUM_CTX")
    ap.add_argument("--think", choices=["auto", "off", "none"], default="auto",
                    help="auto: 모델에 맞게, off: think=False, none: think 인자를 보내지 않음")
    ap.add_argument("--save", default=None, help="결과 전체를 저장할 JSON 파일 경로")
    args = ap.parse_args()

    llm_client.MODEL = args.model                  # llm_client.generate는 호출할 때 이 값을 읽는다
    if args.num_ctx:
        llm_client.NUM_CTX = args.num_ctx
    if args.think == "none" or (args.think == "auto" and args.model.lower().startswith(NO_THINK_PREFIXES)):
        llm_client.THINK = None
    path = Path(args.source)
    text = "\n\n".join(text_cleaner.extract_pages(str(path)))
    try:
        res = run_smoke(text, args.content_type, args.duration)
    except Exception as exc:  # Ollama가 꺼져 있거나 모델이 없을 때 원인을 그대로 보여 준다
        print(f"실행하지 못했습니다: {exc}")
        print("Ollama가 켜져 있는지(ollama list), 모델을 받아 두었는지(ollama pull 모델이름) 확인해 주세요.")
        return 1
    print_report(args.model, res)
    if args.save:
        Path(args.save).write_text(json.dumps({"model": args.model, "num_ctx": llm_client.NUM_CTX,
                                               "table": stage_table(res), **res},
                                              ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        print(f"\n결과를 저장했습니다: {args.save}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
