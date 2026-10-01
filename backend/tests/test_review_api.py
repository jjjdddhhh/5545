# 검수 저장, 자동 수정, 수정·재생성 규칙, 사람 확인, 프롬프트 버전 테스트(TEST_DATABASE_URL이 있을 때만).
from sqlalchemy import select

from app.db import models as m
from app.llm import llm_client
from tests.fake_llm import FakeOllama
from tests.test_runner_api import fake, setup_project, wait_run  # noqa: F401


def run(client, content_type="both"):
    pid = setup_project(client, content_type=content_type)
    r = wait_run(client, client.post(f"/api/projects/{pid}/runs").json()["run_id"])
    assert r["status"] == "done", r["error_message"]
    return pid, r["id"]


def codes(view, result):
    return sorted({c["check_code"] for c in view["auto"] if c["result"] == result})


def test_checks_saved_with_policy_and_c10_candidates(client, db, fake):
    pid, run_id = run(client)
    view = client.get(f"/api/runs/{run_id}/checks").json()
    assert {c["check_code"] for c in view["auto"]} == {f"C{i:02d}" for i in range(1, 13)}
    assert [h["check_code"] for h in view["human"]] == ["H01", "H02", "H03"]
    assert all(h["result"] == "unchecked" for h in view["human"])
    assert codes(view, "fail") == []
    # 가짜 매뉴얼의 주의사항은 장갑 문장 하나뿐이라, 원고의 다른 경고 문장(보안경 착용 등)이 후보로 추가된다
    c10 = next(c for c in view["auto"] if c["check_code"] == "C10")
    assert c10["result"] == "warn" and "후보로 추가" in c10["message"]
    rule = db.scalars(select(m.Caution).where(m.Caution.source == "rule")).all()
    assert rule and all(c.manual_id for c in rule)
    assert view["summary"]["total"] == len(view["auto"])

    # 다시 검수하면 추가된 후보가 경고 문장을 덮으므로 C10이 통과한다
    again = client.post(f"/api/runs/{run_id}/checks/recheck").json()
    assert next(c for c in again["auto"] if c["check_code"] == "C10")["result"] == "pass"
    assert [c for c in again["auto"] if c["check_code"] == "C01"][0]["result"] == "pass"   # C01은 그대로 남는다


def test_broken_subtitles_are_fixed_automatically(client, db, fake):
    pid, run_id = run(client, "video")
    cue = db.scalars(select(m.SubtitleCue).order_by(m.SubtitleCue.id)).first()
    cue.body = "가" * 30          # 16자 초과(C06)
    cue.end_ms = cue.end_ms - 1   # 첫 자막의 끝을 1ms 당겨 시간도 흐트러뜨린다(자동 수정 때 함께 다시 계산된다)
    db.commit()
    view = client.post(f"/api/runs/{run_id}/checks/recheck").json()
    c06 = [c for c in view["auto"] if c["check_code"] == "C06" and c["target_id"] == cue.narration_id][0]
    assert c06["result"] == "pass" and c06["message"].startswith("자동으로 고쳤습니다")
    db.expire_all()
    assert all(len(line) <= 16 for c in db.scalars(select(m.SubtitleCue)) for line in c.body.split("\n"))


def test_patch_scene_then_regenerate_keeps_user_fields(client, db, fake):
    pid, run_id = run(client, "video")
    sc = client.get(f"/api/projects/{pid}/outline").json()["scenes"][0]
    r = client.patch(f"/api/scenes/{sc['id']}", json={"screen_description": "사용자가 고친 화면 설명", "title": sc["title"]})
    out = r.json()
    assert out["edited_fields"] == ["screen_description"]               # 같은 값으로 보낸 title은 기록하지 않는다
    client.patch(f"/api/narrations/{out['narration']['id']}", json={"body": "보안경과 장갑을 반드시 착용합니다."})

    before = len(fake.calls)
    r = client.post(f"/api/scenes/{sc['id']}/regenerate", json={"parts": ["detail", "narration"]})
    assert r.status_code == 200
    body = r.json()
    assert body["scene"]["screen_description"] == "사용자가 고친 화면 설명"   # 사용자가 고친 필드는 덮어쓰지 않는다
    assert body["scene"]["visual_suggestion"]                              # 나머지는 다시 만든다
    assert body["regenerated"] == ["detail"] and set(body["kept"]) == {"screen_description", "narration"}
    assert len(fake.calls) == before + 1                                   # 고친 내레이션은 다시 만들지 않는다
    assert "사용자가 고친 화면 설명" in fake.calls[-1]["messages"][1]["content"]   # 고정값으로 프롬프트에 넘긴다
    revs = db.scalars(select(m.Revision.field_name)).all()
    assert sorted(revs) == ["body", "screen_description"]


def test_regenerate_reports_ollama_error(client, monkeypatch, fake):
    pid, _ = run(client, "video")
    sc = client.get(f"/api/projects/{pid}/outline").json()["scenes"][0]

    def down(**kw):
        raise ConnectionError("연결 거부")
    monkeypatch.setattr(llm_client.client, "chat", down)
    r = client.post(f"/api/scenes/{sc['id']}/regenerate", json={"parts": ["detail"]})
    assert r.status_code == 502 and "Ollama" in r.json()["detail"]


def test_scene_order_and_add_scene(client, db, fake):
    pid, run_id = run(client, "video")
    scenes = client.get(f"/api/projects/{pid}/outline").json()["scenes"]
    ids = [s["id"] for s in scenes]
    new_order = [ids[2], ids[0], ids[1], ids[3]]
    view = client.put(f"/api/projects/{pid}/scene-order", json={"scene_ids": new_order}).json()
    assert [s["id"] for s in view["scenes"]] == new_order and [s["seq"] for s in view["scenes"]] == [1, 2, 3, 4]
    assert client.put(f"/api/projects/{pid}/scene-order", json={"scene_ids": ids[:3]}).status_code == 400

    r = client.post(f"/api/projects/{pid}/scenes", json={"title": "정리 체조", "source_paragraphs": ["p99"]})
    assert r.status_code == 400
    r = client.post(f"/api/projects/{pid}/scenes", json={"title": "정리 체조", "source_paragraphs": ["p2"]})
    added = r.json()
    assert added["seq"] == 5 and added["duration_sec"] == 30 and added["char_budget"] == 150
    assert added["start_sec"] == 120
    view = client.get(f"/api/runs/{run_id}/checks").json()
    assert next(c for c in view["auto"] if c["check_code"] == "C02")["result"] == "warn"   # 장면 수가 계산과 달라졌다


def test_human_checks(client, fake):
    pid, run_id = run(client, "video")
    view = client.put(f"/api/runs/{run_id}/human-checks/h02", json={"checked": True, "note": "용어 수준 적절"}).json()
    h02 = next(h for h in view["human"] if h["check_code"] == "H02")
    assert h02["result"] == "pass" and h02["checked_by"] == 1 and h02["checked_at"] and h02["message"] == "용어 수준 적절"
    view = client.put(f"/api/runs/{run_id}/human-checks/H02", json={"checked": False}).json()
    h02 = next(h for h in view["human"] if h["check_code"] == "H02")
    assert h02["result"] == "unchecked" and h02["checked_by"] is None
    assert client.put(f"/api/runs/{run_id}/human-checks/C01", json={"checked": True}).status_code == 400


def test_prompt_versions_used_by_runs(client, db, fake):
    view = client.get("/api/prompts/outline").json()
    assert view["source"] == "file" and "scene_count" in view["placeholders"]
    assert client.get("/api/prompts/quiz").status_code == 404

    new_system = view["system_prompt"].replace("{keywords}", "없음") + "\n10. 장면 제목은 10자 이내로 쓴다."
    saved = client.put("/api/prompts/outline", json={"system_prompt": new_system,
                                                      "user_template": view["user_template"]}).json()
    assert saved["version"] == 2 and saved["source"] == "db"
    assert [v["version"] for v in saved["versions"]] == [1, 2]
    assert any("keywords" in w for w in saved["warnings"])              # 빠진 변수를 알려 준다

    pid, run_id = run(client, "video")
    tid = db.scalar(select(m.AgentStepLog.prompt_template_id).where(m.AgentStepLog.run_id == run_id,
                                                                    m.AgentStepLog.stage == "outline"))
    assert db.get(m.PromptTemplate, tid).version == 2                   # 실행 로그에 쓴 버전이 남는다
    assert "10자 이내" in fake.calls[0]["messages"][0]["content"]

    back = client.post("/api/prompts/outline/versions/1/activate").json()
    assert back["version"] == 1 and back["source"] == "db"
