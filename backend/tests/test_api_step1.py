# 단계 1 API 테스트: 프로젝트, 원고 입력, 문단 고치기, 생성 조건, 상태 확인(TEST_DATABASE_URL이 있을 때만).
import pytest


def make_project(client, title="신입 안전교육 · 전동드릴 사용법"):
    r = client.post("/api/projects", json={"title": title})
    assert r.status_code == 201
    return r.json()


def test_project_create_list_search(client):
    a = make_project(client)
    make_project(client, "현장 관리자 교육")
    assert len(client.get("/api/projects").json()) == 2
    found = client.get("/api/projects", params={"q": "전동드릴"}).json()
    assert [p["id"] for p in found] == [a["id"]]                     # 제목 검색
    assert client.get("/api/projects", params={"q": "%"}).json() == []  # LIKE 특수문자는 글자 그대로 찾는다
    detail = client.get(f"/api/projects/{a['id']}").json()
    assert detail["status"] == "draft" and detail["source"] is None
    assert client.get("/api/projects/9999").status_code == 404


def test_paste_source_preview_and_paragraph_edit(client):
    p = make_project(client)
    text = "보호구 착용 기준\n\n작업 종류에 따라 착용할 보호구가 다르다. 보안경과 장갑을 반드시 착용한다. 헐렁한 장갑은 쓰지 않는다."
    r = client.post(f"/api/projects/{p['id']}/sources", data={"text": text})
    assert r.status_code == 201
    src = r.json()
    assert src["raw_text"] == text and src["source_type"] == "paste"
    assert [x["kind"] for x in src["paragraphs"]] == ["heading", "body"]
    assert src["stats"]["paragraphs"] == 2

    # 두 문단을 하나로 합치면 번호가 p1 하나로 다시 매겨진다
    merged = [{"kind": "body", "text": src["paragraphs"][0]["text"] + " " + src["paragraphs"][1]["text"]}]
    r = client.put(f"/api/sources/{src['id']}/paragraphs", json={"paragraphs": merged})
    assert r.status_code == 200
    out = r.json()
    assert out["id"] == src["id"]                                    # 아직 실행이 없으므로 같은 행을 고친다
    assert [x["id"] for x in out["paragraphs"]] == ["p1"]
    assert client.get(f"/api/projects/{p['id']}/sources/latest").json()["paragraphs"][0]["id"] == "p1"


def test_file_upload_and_hwp_rejected(client):
    p = make_project(client)
    r = client.post(f"/api/projects/{p['id']}/sources",
                    files={"file": ("교안.txt", "보안경은 작업 내내 쓴다. 벗으면 파편이 눈에 들어갈 수 있다.".encode("cp949"))})
    assert r.status_code == 201 and r.json()["file_name"] == "교안.txt"
    r = client.post(f"/api/projects/{p['id']}/sources", files={"file": ("교안.hwp", b"\x00\x01")})
    assert r.status_code == 400 and "hwpx" in r.json()["detail"]
    assert client.post(f"/api/projects/{p['id']}/sources", data={"text": "   "}).status_code == 400


def test_settings_validation_and_history(client):
    p = make_project(client)
    base = {"content_type": "both", "audience": "신입 사원", "difficulty": "beginner"}
    r = client.put(f"/api/projects/{p['id']}/settings", json=base)
    assert r.status_code == 422                                      # 분량과 장면 수가 모두 없다
    r1 = client.put(f"/api/projects/{p['id']}/settings",
                    json={**base, "target_duration_sec": 150, "keywords": [" 보호장갑 ", "보호장갑", ""]})
    assert r1.status_code == 200
    assert r1.json()["keywords"] == ["보호장갑"] and r1.json()["narration_cpm"] == 300
    r2 = client.put(f"/api/projects/{p['id']}/settings", json={**base, "scene_count": 4})
    assert r2.json()["id"] != r1.json()["id"]                        # 설정은 새 행으로 쌓인다
    assert client.get(f"/api/projects/{p['id']}/settings").json()["scene_count"] == 4


def test_health_reports_db_ok(client):
    body = client.get("/api/health").json()
    assert body["db"]["ok"] is True
    assert "ok" in body["ollama"]                                    # Ollama가 없어도 500이 아니다
