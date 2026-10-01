# 구성안과 장면 상세 단계 테스트(DB 없이). 가짜 Ollama로 재요청 규칙과 긴 원고 요약 경로를 확인한다.
from types import SimpleNamespace

import pytest

from app.llm import llm_client
from app.llm.prompt_store import file_prompt, render
from app.pipeline import outline, scene_detail
from app.pipeline.llm_step import ListRecorder
from tests.fake_llm import FakeOllama, default_answer

SETTING = SimpleNamespace(audience="신입 사원", difficulty="beginner", output_language="ko", tone=None,
                          keywords=["보호장갑"])
PARAS = [{"id": f"p{i}", "kind": "body", "text": f"문단 {i}의 내용이다. 보안경을 쓴다."} for i in range(1, 6)]


def test_render_keeps_unknown_braces():
    assert render("{a}와 {b} 그리고 {\"x\": 1}", {"a": 1}) == "1와 {b} 그리고 {\"x\": 1}"


def test_outline_ok_without_retry(monkeypatch):
    fake = FakeOllama()
    monkeypatch.setattr(llm_client.client, "chat", fake)
    rec = ListRecorder()
    res = outline.generate_outline(rec, file_prompt("outline"), SETTING, PARAS, scene_count=3)
    assert len(res.outline.scenes) == 3 and not res.retried and not res.failures
    assert "<source>" in fake.calls[0]["messages"][1]["content"]        # 원고는 source 태그로 넘긴다
    assert "정확히 3개" in fake.calls[0]["messages"][0]["content"]
    assert rec.rows[0]["stage"] == "outline" and rec.rows[0]["output_json"]["output"]["title"]


def test_outline_retries_once_on_wrong_count_and_bad_paragraph(monkeypatch):
    def bad_then_good(kw, n):
        ans = default_answer("OutlineOut", kw)
        if n == 1:
            ans["scenes"] = ans["scenes"][:2]                       # 장면 수가 틀림(C02)
            ans["scenes"][0]["source_paragraphs"] = ["p99"]          # 없는 문단(C03)
        return ans
    fake = FakeOllama({"OutlineOut": bad_then_good})
    monkeypatch.setattr(llm_client.client, "chat", fake)
    res = outline.generate_outline(ListRecorder(), file_prompt("outline"), SETTING, PARAS, scene_count=3)
    assert res.retried and not res.failures and len(res.outline.scenes) == 3
    feedback = fake.calls[1]["messages"][1]["content"]
    assert "장면 수가 2개" in feedback and "p99" in feedback            # 무엇이 틀렸는지 알려 주고 다시 요청한다


def test_outline_still_failing_is_reported_and_normalized(monkeypatch):
    def always_bad(kw, n):
        ans = default_answer("OutlineOut", kw)
        ans["scenes"][0]["source_paragraphs"] = ["p99"]
        ans["scenes"][1]["seq"] = 7
        return ans
    monkeypatch.setattr(llm_client.client, "chat", FakeOllama({"OutlineOut": always_bad}))
    res = outline.generate_outline(ListRecorder(), file_prompt("outline"), SETTING, PARAS, scene_count=3)
    assert [f.code for f in res.failures] == ["C03"]                  # 1회만 다시 요청하고 남은 실패를 넘긴다
    assert res.outline.scenes[0].source_paragraphs == []             # 없는 번호는 지운다
    assert [s.seq for s in res.outline.scenes] == [1, 2, 3]          # 순서는 코드가 다시 매긴다


def test_long_source_is_summarized_by_chunks(monkeypatch):
    fake = FakeOllama()
    monkeypatch.setattr(llm_client.client, "chat", fake)
    monkeypatch.setattr(llm_client, "NUM_CTX", 3000)                   # 원고 몫을 1000토큰으로 줄인다
    long_paras = [{"id": f"p{i}", "kind": "body", "text": "가" * 300} for i in range(1, 11)]  # 3000자
    res = outline.generate_outline(ListRecorder(), file_prompt("outline"), SETTING, long_paras, scene_count=2)
    assert res.summarized
    assert fake.titles().count("ChunkSummaryOut") >= 3 and fake.titles()[-1] == "OutlineOut"
    assert "[p1] p1 요점" in fake.calls[-1]["messages"][1]["content"]  # 요약본도 문단 번호를 지닌다


def test_truncation_warning_triggers_summary(monkeypatch):
    fake = FakeOllama(prompt_tokens=llm_client.NUM_CTX)                # Ollama가 한도를 꽉 채웠다고 알린다
    monkeypatch.setattr(llm_client.client, "chat", fake)
    res = outline.generate_outline(ListRecorder(), file_prompt("outline"), SETTING, PARAS, scene_count=2)
    assert res.summarized and "ChunkSummaryOut" in fake.titles()


def test_scene_detail_keeps_user_edited_fields(monkeypatch):
    fake = FakeOllama()
    monkeypatch.setattr(llm_client.client, "chat", fake)
    sc = scene_detail.SceneInput(seq=2, title="보호구", key_point="장갑을 낀다", duration_sec=30,
                                 source_paragraphs=["p2"], fixed={"screen_description": "사용자가 쓴 화면 설명"})
    res = scene_detail.generate_scene_detail(ListRecorder(), file_prompt("scene_detail"), SETTING, "제목", sc,
                                             {p["id"]: p for p in PARAS})
    assert res.detail.screen_description == "사용자가 쓴 화면 설명"    # 결과에서도 덮어쓰지 않는다
    user = fake.calls[0]["messages"][1]["content"]
    assert "사용자가 쓴 화면 설명" in user and "[p2]" in user and "[p3]" not in user  # 고정값과 근거 문단만 넘긴다


def test_scene_detail_language_retry(monkeypatch):
    english = {"screen_description": "Show the battery being inserted closely.",
               "visual_suggestion": "Close-up shot of the battery", "on_screen_text": "Check the battery"}
    fake = FakeOllama({"SceneDetailOut": lambda kw, n: english if n == 1 else default_answer("SceneDetailOut", kw)})
    monkeypatch.setattr(llm_client.client, "chat", fake)
    sc = scene_detail.SceneInput(1, "도입", "개요", 30, ["p1"])
    res = scene_detail.generate_scene_detail(ListRecorder(), file_prompt("scene_detail"), SETTING, "제목", sc,
                                             {p["id"]: p for p in PARAS})
    assert res.retried and not res.failures and len(fake.calls) == 2  # C11 실패로 1회 다시 요청
