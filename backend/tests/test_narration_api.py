# 내레이션·자막·SRT 통합 테스트(TEST_DATABASE_URL이 있을 때만).
from sqlalchemy import select

from app.db import models as m
from tests.test_runner_api import fake, setup_project, wait_run  # noqa: F401  fake는 픽스처로 쓴다


def test_video_run_creates_narration_cues_and_srt(client, db, fake):
    pid = setup_project(client, content_type="video")
    run = wait_run(client, client.post(f"/api/projects/{pid}/runs").json()["run_id"])
    assert run["status"] == "done", run["error_message"]
    scenes = client.get(f"/api/projects/{pid}/outline").json()["scenes"]
    for sc in scenes:
        assert sc["narration"]["char_count"] == sc["char_budget"]          # 가짜 모델은 예산에 딱 맞게 쓴다
        assert sc["cues"][0]["start_ms"] == 0 and sc["cues"][-1]["end_ms"] == sc["duration_sec"] * 1000
        assert all(len(line) <= 16 for c in sc["cues"] for line in c["body"].split("\n"))

    r = client.get(f"/api/projects/{pid}/export", params={"format": "srt"})
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    text = r.content.decode("utf-8-sig")
    assert text.startswith("1\r\n00:00:00,000 --> ")
    assert "00:01:30," in text or "00:01:3" in text                       # 4번째 장면(90초 시작)까지 누적


def test_patch_narration_resplits_and_records_revision(client, db, fake):
    pid = setup_project(client, content_type="video")
    wait_run(client, client.post(f"/api/projects/{pid}/runs").json()["run_id"])
    sc = client.get(f"/api/projects/{pid}/outline").json()["scenes"][0]
    new = "보안경과 장갑을 반드시 착용합니다. 헐렁한 장갑은 쓰지 않습니다."
    r = client.patch(f"/api/narrations/{sc['narration']['id']}", json={"body": new})
    assert r.status_code == 200
    out = r.json()
    assert out["narration"]["body"] == new and out["narration"]["is_edited"] is True
    assert " ".join(c["body"].replace("\n", " ") for c in out["cues"]) == new   # LLM 없이 코드로 다시 나눴다
    assert out["cues"][-1]["end_ms"] == sc["duration_sec"] * 1000
    rev = db.scalars(select(m.Revision)).all()
    assert len(rev) == 1 and rev[0].entity_type == "narration" and rev[0].after_value == new
    assert client.patch("/api/narrations/9999", json={"body": "x"}).status_code == 404


def test_manual_only_run_has_no_srt(client, fake):
    pid = setup_project(client, content_type="manual")
    run = wait_run(client, client.post(f"/api/projects/{pid}/runs").json()["run_id"])
    assert run["status"] == "done"
    assert client.get(f"/api/projects/{pid}/export", params={"format": "srt"}).status_code == 404
    assert client.get(f"/api/projects/{pid}/export", params={"format": "xyz"}).status_code == 400
