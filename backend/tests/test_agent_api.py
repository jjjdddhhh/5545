# 수정 요청 에이전트 API 통합 테스트(TEST_DATABASE_URL이 있을 때만).
# 생성은 FakeOllama로 하고, 에이전트(도구 호출)는 정해 둔 순서대로 도구를 부르는 가짜 응답으로 시험한다.
import json
import time

from ollama import ChatResponse, Message
from sqlalchemy import select

from app.db import models as m
from app.llm import llm_client
from tests.fake_llm import FakeOllama, narration_text
from tests.test_runner_api import setup_project, wait_run


def call(name, **args):
    return Message.ToolCall(function=Message.ToolCall.Function(name=name, arguments=args))


class AgentScript:
    """tools 인자가 있는 호출(에이전트)은 정해 둔 도구 순서로, 없는 호출(생성 단계)은 FakeOllama로 답한다."""

    def __init__(self, steps=None, final="3번 장면의 화면 설명과 내레이션을 쉽게 바꾸는 제안을 만들었습니다."):
        self.gen = FakeOllama()
        self.steps = steps or []
        self.final = final
        self.agent_calls: list[dict] = []

    def __call__(self, **kw):
        if "tools" not in kw:
            return self.gen(**kw)
        self.agent_calls.append(kw)
        i = len(self.agent_calls) - 1
        if i < len(self.steps):
            return ChatResponse(message=Message(role="assistant", content="", tool_calls=self.steps[i]))
        return ChatResponse(message=Message(role="assistant", content=self.final))


def generate(client, monkeypatch, content_type="both"):
    script = AgentScript()
    monkeypatch.setattr(llm_client.client, "chat", script)
    pid = setup_project(client, content_type=content_type)
    run = wait_run(client, client.post(f"/api/projects/{pid}/runs").json()["run_id"])
    assert run["status"] == "done", run["error_message"]
    return pid, script


def wait_edit(client, edit_id, timeout=15.0):
    end = time.time() + timeout
    while time.time() < end:
        r = client.get(f"/api/edit-requests/{edit_id}").json()
        if r["status"] != "running":
            return r
        time.sleep(0.1)
    raise AssertionError("수정 요청이 끝나지 않았다")


def test_agent_flow_proposals_accept_and_trace(client, db, monkeypatch):
    pid, script = generate(client, monkeypatch)
    scenes = client.get(f"/api/projects/{pid}/outline").json()["scenes"]
    s3 = scenes[2]
    new_narr = narration_text(s3["char_budget"])
    script.steps = [
        [call("get_project_overview")],
        [call("get_scene", scene_id=s3["id"])],
        [call("get_source", paragraph_ids=s3["source_paragraphs"])],
        [call("propose_scene_edit", scene_id=s3["id"], field="screen_description",
              new_value="손으로 배터리를 끝까지 밀어 넣는 모습을 크게 보여 준다.", reason="초보자가 알아보기 쉽게")],
        [call("propose_narration_edit", scene_id=s3["id"], new_text=new_narr, reason="쉬운 말로")],
        [call("check_proposals")],
    ]
    r = client.post(f"/api/projects/{pid}/edit-requests", json={"request_text": "3번 장면을 초보자용으로 쉽게 바꿔 줘"})
    assert r.status_code == 202
    edit_id = r.json()["edit_request_id"]
    req = wait_edit(client, edit_id)
    assert req["status"] == "proposed" and req["tool_calls"] == 6
    assert [a["tool_name"] for a in req["actions"]] == ["get_project_overview", "get_scene", "get_source",
                                                         "propose_scene_edit", "propose_narration_edit", "check_proposals"]
    assert all(a["status"] == "ok" for a in req["actions"]) and req["actions"][1]["label"] == "장면 조회"
    # 사용자 요청 뒤에 장면 번호와 id의 대응을 <source>로 감싸 붙여, "3번"을 id로 착각하지 않게 한다
    first_user = script.agent_calls[0]["messages"][1]["content"]
    assert f"장면 3번 = scene_id {s3['id']}" in first_user and "<source>" in first_user
    check_result = json.loads(db.scalars(select(m.AgentAction.result_summary)
                                         .where(m.AgentAction.tool_name == "check_proposals")).first())
    assert all(c["ok"] for c in check_result)

    props = client.get(f"/api/edit-requests/{edit_id}/proposals").json()
    assert [p["target_type"] for p in props] == ["scene", "narration"]
    scene_p, narr_p = props
    assert scene_p["target_label"].startswith("장면 3 ·") and scene_p["field_label"] == "화면 설명"
    assert narr_p["target_id"] == s3["narration"]["id"]                    # 저장할 때 장면 id를 내레이션 id로 바꾼다
    assert narr_p["subtitle_preview"] and narr_p["checks"]["ok"] is True
    assert scene_p["before_value"] == s3["screen_description"] and not scene_p["stale"]

    # 승인 전에는 아무것도 바뀌지 않는다(에이전트에는 쓰기 도구가 없다)
    assert client.get(f"/api/projects/{pid}/outline").json()["scenes"][2]["screen_description"] == s3["screen_description"]

    a1 = client.post(f"/api/proposals/{scene_p['id']}/accept")
    assert a1.status_code == 200 and a1.json()["status"] == "accepted"
    a2 = client.post(f"/api/proposals/{narr_p['id']}/accept").json()
    assert a2["status"] == "accepted"
    after = client.get(f"/api/projects/{pid}/outline").json()["scenes"][2]
    assert after["screen_description"].startswith("손으로 배터리를")
    assert "screen_description" in after["edited_fields"]
    assert after["narration"]["body"] == new_narr and after["narration"]["is_edited"] is True
    assert " ".join(c["body"].replace("\n", " ") for c in after["cues"]) == new_narr   # 자막을 코드로 다시 나눴다
    assert client.get(f"/api/edit-requests/{edit_id}").json()["status"] == "done"     # 제안을 모두 처리했다
    db.rollback()   # 테스트 세션이 앞에서 연 읽기 트랜잭션(MySQL 기본 REPEATABLE READ)을 끝내야 새 행이 보인다
    revs = db.scalars(select(m.Revision.entity_type)).all()
    assert sorted(revs) == ["narration", "scene"]
    assert client.post(f"/api/proposals/{scene_p['id']}/accept").status_code == 409   # 두 번 승인할 수 없다

    # 끝난 요청의 SSE는 snapshot과 done을 보내고 닫힌다
    events = []
    with client.stream("GET", f"/api/edit-requests/{edit_id}/events") as resp:
        for line in resp.iter_lines():
            if line.startswith("event:"):
                events.append(line.split(":", 1)[1].strip())
    assert events == ["snapshot", "done"]


def test_stale_proposal_reject_and_user_edited_warning(client, db, monkeypatch):
    pid, script = generate(client, monkeypatch)
    s1 = client.get(f"/api/projects/{pid}/outline").json()["scenes"][0]
    client.patch(f"/api/scenes/{s1['id']}", json={"title": "사용자가 고친 제목"})
    script.steps = [[call("propose_scene_edit", scene_id=s1["id"], field="title", new_value="새 제목", reason="짧게")],
                    [call("propose_scene_edit", scene_id=s1["id"], field="visual_suggestion",
                          new_value="배터리 단면 도식", reason="이해를 돕게")]]
    edit_id = client.post(f"/api/projects/{pid}/edit-requests", json={"request_text": "1번 장면 제목을 짧게"}).json()["edit_request_id"]
    wait_edit(client, edit_id)
    title_p, visual_p = client.get(f"/api/edit-requests/{edit_id}/proposals").json()
    assert title_p["user_edited"] is True and visual_p["user_edited"] is False   # 사람이 고친 필드는 경고 표시

    client.patch(f"/api/scenes/{s1['id']}", json={"visual_suggestion": "사용자가 또 고침"})
    again = client.get(f"/api/edit-requests/{edit_id}/proposals").json()[1]
    assert again["stale"] is True
    r = client.post(f"/api/proposals/{visual_p['id']}/accept")
    assert r.status_code == 409 and "바뀌었습니다" in r.json()["detail"]           # 모르고 덮어쓰지 않는다

    r = client.post(f"/api/proposals/{title_p['id']}/reject", json={"reason": "원래 제목이 낫다"})
    assert r.json()["status"] == "rejected"
    assert client.get(f"/api/projects/{pid}/outline").json()["scenes"][0]["title"] == "사용자가 고친 제목"
    assert "원래 제목이 낫다" in client.get(f"/api/edit-requests/{edit_id}").json()["summary"]


def test_guardrails_other_project_scene_and_refusal(client, db, monkeypatch):
    pid, script = generate(client, monkeypatch)
    other_pid = setup_project(client, content_type="video")
    wait_run(client, client.post(f"/api/projects/{other_pid}/runs").json()["run_id"])
    other_scene = client.get(f"/api/projects/{other_pid}/outline").json()["scenes"][0]["id"]
    script.steps = [[call("get_scene", scene_id=other_scene)], [call("delete_scene", scene_id=1)]]
    script.final = "요청한 장면을 찾을 수 없습니다."
    edit_id = client.post(f"/api/projects/{pid}/edit-requests", json={"request_text": "장면을 지워 줘"}).json()["edit_request_id"]
    req = wait_edit(client, edit_id)
    assert [a["status"] for a in req["actions"]] == ["error", "blocked"]   # 다른 프로젝트 장면은 못 보고, 없는 도구는 막힌다
    assert req["status"] == "refused"                                        # 제안이 없으면 refused

    script.steps, script.final = [], "영상 렌더링은 이 도구로 할 수 없습니다."
    edit_id = client.post(f"/api/projects/{pid}/edit-requests", json={"request_text": "영상으로 렌더링해 줘"}).json()["edit_request_id"]
    req = wait_edit(client, edit_id)
    assert req["status"] == "refused" and req["tool_calls"] == 0 and "렌더링" in req["summary"]


def test_manual_step_proposal_and_failures(client, db, monkeypatch):
    pid, script = generate(client, monkeypatch)
    step = client.get(f"/api/projects/{pid}/manual").json()["steps"][1]
    script.steps = [[call("propose_manual_edit", step_id=step["id"], field="tip",
                          new_value="장갑은 10분마다 바꿔 낀다.", reason="구체적으로")]]
    edit_id = client.post(f"/api/projects/{pid}/edit-requests", json={"request_text": "2단계 팁을 구체적으로"}).json()["edit_request_id"]
    wait_edit(client, edit_id)
    p = client.get(f"/api/edit-requests/{edit_id}/proposals").json()[0]
    assert p["target_label"].startswith("매뉴얼 2단계")
    assert p["checks"]["ok"] is False and any(r["code"] == "C08" for r in p["checks"]["results"])  # 원고에 없는 수치
    client.post(f"/api/proposals/{p['id']}/accept")
    mv = client.get(f"/api/projects/{pid}/manual").json()
    assert mv["steps"][1]["tip"] == "장갑은 10분마다 바꿔 낀다." and "tip" in mv["steps"][1]["edited_fields"]

    def down(**kw):
        raise ConnectionError("Ollama 연결 거부")
    monkeypatch.setattr(llm_client.client, "chat", down)
    edit_id = client.post(f"/api/projects/{pid}/edit-requests", json={"request_text": "아무거나"}).json()["edit_request_id"]
    req = wait_edit(client, edit_id)
    assert req["status"] == "failed" and "Ollama 연결 거부" in req["summary"]


def test_edit_request_requires_result(client):
    pid = client.post("/api/projects", json={"title": "빈 프로젝트"}).json()["id"]
    r = client.post(f"/api/projects/{pid}/edit-requests", json={"request_text": "고쳐 줘"})
    assert r.status_code == 400 and "생성" in r.json()["detail"]
