# 평가 스크립트 테스트. 채점은 DB 없이, 지표 추출은 TEST_DATABASE_URL이 있을 때만 확인한다.
import json

from app.config import REPO_ROOT
from scripts import report_metrics, run_eval

ITEM = {"id": "R01", "type": "easy", "target": {"kind": "scene", "seq": [3]}, "required_tools": ["get_scene"],
        "allowed_propose_tools": ["propose_scene_edit", "propose_narration_edit"], "should_refuse": False,
        "forbidden_text": []}


def res(props, actions=("get_scene",), status="proposed"):
    return {"status": status, "tool_calls": len(actions) + len(props),
            "actions": [{"tool_name": a, "status": "ok"} for a in actions], "proposals": props, "seconds": 2.0}


def prop(seq, tool="propose_scene_edit", kind="scene", text="쉬운 설명", ok=True):
    return {"target_kind": kind, "target_seq": seq, "tool": tool, "after_value": text, "checks_ok": ok}


def test_score_correct_and_wrong_target():
    assert run_eval.score_item(ITEM, res([prop(3)]))["correct"] is True
    s = run_eval.score_item(ITEM, res([prop(3), prop(4)]))
    assert s["correct"] is False and "엉뚱한 대상" in s["notes"]
    s = run_eval.score_item(ITEM, res([prop(3, tool="propose_manual_edit", kind="manual_step")]))
    assert s["tool_ok"] is False
    assert run_eval.score_item(ITEM, res([prop(3)], actions=()))["notes"].startswith("부르지 않은 도구")


def test_score_refusal_and_injection():
    refuse = {**ITEM, "should_refuse": True, "target": {"kind": "none", "seq": []}, "required_tools": [],
              "allowed_propose_tools": []}
    assert run_eval.score_item(refuse, {"status": "refused", "tool_calls": 0, "actions": [], "proposals": []})["correct"]
    assert not run_eval.score_item(refuse, res([prop(1)]))["correct"]
    inj = {**ITEM, "type": "injection", "forbidden_text": ["테스트"]}
    s = run_eval.score_item(inj, res([prop(3, text="테스트")]))
    assert s["correct"] is False and s["injection_ok"] is False


def test_summary_and_report():
    scores = [run_eval.score_item(ITEM, res([prop(3)])), run_eval.score_item(ITEM, res([prop(5, ok=False)]))]
    summ = run_eval.summarize(scores)
    assert summ["tool_accuracy"] == 0.5 and summ["proposal_pass_rate"] == 0.5 and summ["refusal_accuracy"] is None
    text = run_eval.render_report(scores, summ, "qwen3:8b", 0, 20)
    assert "도구 선택 정확도" in text and "| R01 | easy | O |" in text and "확정되지 않은" in text


def test_requests_json_matches_design_table():
    data = json.loads((REPO_ROOT / "docs" / "eval" / "requests.json").read_text(encoding="utf-8"))
    types = [i["type"] for i in data["items"]]
    assert len(types) == 20
    assert {t: types.count(t) for t in set(types)} == {"easy": 4, "shorten": 4, "keyword": 3, "multi": 3,
                                                       "manual": 3, "out_of_scope": 2, "injection": 1}
    assert all(i["expected_confirmed"] is False for i in data["items"])   # 기대 결과는 사용자가 확정한다


def test_report_metrics_from_db(client, db, monkeypatch):
    from app.llm import llm_client
    from tests.fake_llm import FakeOllama
    from tests.test_runner_api import setup_project, wait_run
    monkeypatch.setattr(llm_client.client, "chat", FakeOllama())
    pid = setup_project(client)
    wait_run(client, client.post(f"/api/projects/{pid}/runs").json()["run_id"])
    sc = client.get(f"/api/projects/{pid}/outline").json()["scenes"][0]
    client.patch(f"/api/scenes/{sc['id']}", json={"title": "고친 제목"})
    db.rollback()
    text = report_metrics.render(db, pid)
    assert "## 프로젝트" in text and "| done |" in text and "전체 1회 (장면 1회)" in text


def test_run_eval_prepare_and_run_one(db, monkeypatch):
    from app.llm import llm_client
    from tests.test_agent_api import AgentScript, call
    script = AgentScript()
    monkeypatch.setattr(llm_client.client, "chat", script)
    pid = run_eval.prepare_project(db, "평가용", run_eval.SAMPLE.read_text(encoding="utf-8"))
    from app.api import deps
    s3 = [s for s in deps.current_outline(db, pid).scenes if s.seq == 3][0]
    script.steps = [[call("get_scene", scene_id=s3.id)],
                    [call("propose_scene_edit", scene_id=s3.id, field="on_screen_text", new_value="배터리 끝까지",
                          reason="쉽게")]]
    out = run_eval.run_one(db, pid, "3번 장면 화면 텍스트를 쉽게")
    assert out["status"] == "proposed" and out["proposals"][0]["target_seq"] == 3
    assert run_eval.score_item(ITEM, out)["correct"] is True
