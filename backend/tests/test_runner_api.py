# 생성 실행 테스트(TEST_DATABASE_URL이 있을 때만). 가짜 Ollama로 실행을 끝까지 돌리고 DB 기록과 SSE를 확인한다.
import json
import time

import pytest
from sqlalchemy import func, select

from app.db import models as m
from app.llm import llm_client
from tests.fake_llm import FakeOllama

SOURCE = """전동드릴 안전교육

작업 전 점검
배터리가 끝까지 끼워졌는지 확인한다. 딸깍 소리가 나야 한다. 비트는 척에 깊이 넣고 척 키로 세 군데를 조인다.

보호구
보안경과 장갑을 반드시 착용한다. 헐렁한 장갑은 회전부에 말려 들어갈 수 있으므로 쓰지 않는다.

작업 자세
드릴은 작업면에 수직으로 유지하고 처음에는 낮은 속도로 3초간 자리를 잡는다. 작업물은 클램프로 고정한다.

정리와 보관
작업이 끝나면 배터리를 먼저 분리하고 비트를 뺀 뒤 케이스에 넣는다. 배터리는 매주 한 번 충전 상태를 점검한다."""


def setup_project(client, content_type="both", **setting):
    pid = client.post("/api/projects", json={"title": "전동드릴 교육"}).json()["id"]
    client.post(f"/api/projects/{pid}/sources", data={"text": SOURCE})
    body = {"content_type": content_type, "audience": "신입 사원", "difficulty": "beginner",
            "target_duration_sec": 120, "keywords": ["보호장갑"], **setting}
    assert client.put(f"/api/projects/{pid}/settings", json=body).status_code == 200
    return pid


def wait_run(client, run_id, timeout=15.0):
    """백그라운드 스레드의 실행이 끝날 때까지 기다린다(가짜 모델이라 보통 1초 안에 끝난다)."""
    end = time.time() + timeout
    while time.time() < end:
        run = client.get(f"/api/runs/{run_id}").json()
        if run["status"] in ("done", "failed"):
            return run
        time.sleep(0.1)
    raise AssertionError("실행이 끝나지 않았다")


def sse_events(client, run_id) -> list[tuple[str, dict]]:
    """끝난 실행의 SSE를 읽는다. snapshot과 done을 보내고 스트림이 닫힌다."""
    out, event = [], None
    with client.stream("GET", f"/api/runs/{run_id}/events") as r:
        for line in r.iter_lines():
            if line.startswith("event:"):
                event = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                out.append((event, json.loads(line.split(":", 1)[1].strip())))
    return out


@pytest.fixture
def fake(monkeypatch):
    f = FakeOllama()
    monkeypatch.setattr(llm_client.client, "chat", f)
    return f


def test_run_end_to_end_and_reconnect(client, db, fake):
    pid = setup_project(client)
    r = client.post(f"/api/projects/{pid}/runs")
    assert r.status_code == 202
    run_id = r.json()["run_id"]
    run = wait_run(client, run_id)
    assert run["status"] == "done", run["error_message"]

    outline = client.get(f"/api/projects/{pid}/outline").json()
    assert len(outline["scenes"]) == 4                                     # 120초 / 30초
    assert outline["total_sec"] == 120
    assert [s["start_sec"] for s in outline["scenes"]] == [0, 30, 60, 90]
    assert all(s["screen_description"] for s in outline["scenes"])
    assert client.get(f"/api/projects/{pid}").json()["status"] == "ready"

    # LLM 호출마다 agent_step_log가 남고, 코드 단계는 prompt_template_id 없이 남는다
    logs = db.execute(select(m.AgentStepLog.stage, func.count()).where(m.AgentStepLog.run_id == run_id)
                      .group_by(m.AgentStepLog.stage)).all()
    counts = dict(logs)
    assert counts["outline"] == 1 and counts["scene_detail"] == 4
    assert counts["budget"] == 1 and counts["clean"] == 1
    assert db.scalar(select(m.AgentStepLog.tokens_in).where(m.AgentStepLog.stage == "outline")) == 500

    # 끝난 뒤 다시 연결해도 DB로 만든 상태(snapshot)와 완료 이벤트를 받는다
    events = sse_events(client, run_id)
    assert [e for e, _ in events] == ["snapshot", "done"]
    snap = events[0][1]
    assert all(s["status"] == "done" for s in snap["stages"])
    assert snap["stages"][3]["stats"]["calls"] == 4
    # 끝난 단계는 모두 걸린 시간을 가진다(늦게 연결해도 화면이 시간을 보여 줄 수 있다)
    assert all(isinstance(s["latency_ms"], int) for s in snap["stages"])


def test_rerun_keeps_previous_result_not_current(client, db, fake):
    pid = setup_project(client)
    first = wait_run(client, client.post(f"/api/projects/{pid}/runs").json()["run_id"])
    first_outline = client.get(f"/api/projects/{pid}/outline").json()["outline"]["id"]
    second = wait_run(client, client.post(f"/api/projects/{pid}/runs").json()["run_id"])
    assert first["status"] == second["status"] == "done"
    rows = db.execute(select(m.Outline.id, m.Outline.is_current).where(m.Outline.project_id == pid)).all()
    assert dict(rows) == {first_outline: False, first_outline + 1: True}   # 이전 결과는 is_current만 false


def test_run_requires_source_and_setting(client):
    pid = client.post("/api/projects", json={"title": "빈 프로젝트"}).json()["id"]
    r = client.post(f"/api/projects/{pid}/runs")
    assert r.status_code == 400 and "원고" in r.json()["detail"]


def test_outline_failure_marks_run_failed(client, monkeypatch):
    monkeypatch.setattr(llm_client.client, "chat", FakeOllama({"OutlineOut": lambda kw, n: '{"title": "x"}'}))
    pid = setup_project(client)
    run = wait_run(client, client.post(f"/api/projects/{pid}/runs").json()["run_id"])
    assert run["status"] == "failed" and "구조화" in run["error_message"]
    assert client.get(f"/api/projects/{pid}").json()["status"] == "error"
    snap = sse_events(client, run["id"])[0][1]
    assert [s["status"] for s in snap["stages"]][:3] == ["done", "done", "failed"]
    assert client.get(f"/api/projects/{pid}/outline").status_code == 404


def test_scene_detail_failure_does_not_stop_run(client, db, monkeypatch):
    # 2번째 장면만 두 번 다 형식 오류를 내면 그 장면만 비고 실행은 끝난다
    from tests.fake_llm import default_answer

    def detail(kw, n):
        return "not json" if n in (2, 3) else default_answer("SceneDetailOut", kw)
    monkeypatch.setattr(llm_client.client, "chat", FakeOllama({"SceneDetailOut": detail}))
    pid = setup_project(client, content_type="video")
    run = wait_run(client, client.post(f"/api/projects/{pid}/runs").json()["run_id"])
    assert run["status"] == "done"
    scenes = client.get(f"/api/projects/{pid}/outline").json()["scenes"]
    assert scenes[1]["screen_description"] is None and scenes[0]["screen_description"]
    c01 = db.scalars(select(m.ReviewCheck).where(m.ReviewCheck.check_code == "C01")).all()
    assert len(c01) == 1 and c01[0].result == "fail" and c01[0].target_id == scenes[1]["id"]
