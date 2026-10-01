# 내레이션 단계 테스트(DB 없이). 글자 수 예산(C04)과 재요청, 군더더기 정리를 확인한다.
from types import SimpleNamespace

from app.llm import llm_client
from app.llm.prompt_store import file_prompt
from app.pipeline import narration as nr
from app.pipeline.llm_step import ListRecorder
from tests.fake_llm import FakeOllama, default_answer, narration_text

SETTING = SimpleNamespace(audience="신입 사원", difficulty="beginner", output_language="ko", tone=None, keywords=[])
SCENE = nr.NarrationInput(seq=1, title="작업 전 점검", key_point="배터리를 확인한다", screen_description="손 클로즈업",
                          on_screen_text="배터리 확인", duration_sec=30, char_budget=150, source_paragraphs=["p1"])
PARAS = {"p1": {"id": "p1", "kind": "body", "text": "배터리가 끝까지 끼워졌는지 확인한다."}}


def test_clean_narration_removes_directions():
    assert nr.clean_narration('내레이션: "드릴을 켭니다. (화면: 손 클로즈업) 확인합니다."') == "드릴을 켭니다. 확인합니다."


def test_budget_check_boundaries():
    assert nr.check_budget("가" * 128, 150).result == "pass"
    r = nr.check_budget("가" * 100, 150)
    assert r.result == "fail" and "128~172자" in r.message and "짧습니다" in r.message


def test_prompt_has_numeric_range_and_ok(monkeypatch):
    fake = FakeOllama()
    monkeypatch.setattr(llm_client.client, "chat", fake)
    res = nr.generate_narration(ListRecorder(), file_prompt("narration"), SETTING, SCENE, PARAS)
    assert not res.retried and len(res.text.replace(" ", "")) == 150
    assert "128자보다 짧거나 172자보다 길면" in fake.calls[0]["messages"][0]["content"]


def test_too_short_narration_is_retried_once(monkeypatch):
    fake = FakeOllama({"NarrationOut": lambda kw, n: {"narration": "짧다."} if n == 1 else default_answer("NarrationOut", kw)})
    monkeypatch.setattr(llm_client.client, "chat", fake)
    res = nr.generate_narration(ListRecorder(), file_prompt("narration"), SETTING, SCENE, PARAS)
    assert res.retried and not res.failures
    assert "짧습니다" in fake.calls[1]["messages"][1]["content"]


def test_still_failing_narration_is_kept_with_failure(monkeypatch):
    fake = FakeOllama({"NarrationOut": lambda kw, n: {"narration": narration_text(300)}})
    monkeypatch.setattr(llm_client.client, "chat", fake)
    res = nr.generate_narration(ListRecorder(), file_prompt("narration"), SETTING, SCENE, PARAS, ref=7)
    assert len(fake.calls) == 2 and res.failures[0].code == "C04" and res.failures[0].target_ref == 7
