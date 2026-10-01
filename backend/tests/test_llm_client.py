# llm_client 테스트. 실제 Ollama를 부르지 않고 가짜 응답으로 재요청 규칙(설계서 10절 C01)을 확인한다.
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from app.llm import llm_client


class Scene(BaseModel):
    seq: int
    title: str
    key_point: str
    source_paragraphs: list[str]


class OutlineOut(BaseModel):
    title: str
    summary: str
    learning_objectives: list[str]
    scenes: list[Scene]


GOOD = ('{"title":"t","summary":"s","learning_objectives":["a"],'
        '"scenes":[{"seq":1,"title":"x","key_point":"k","source_paragraphs":["p1"]}]}')
BAD = '{"title":"t"}'


def fake(contents, prompt_tokens=100):
    calls = []

    def chat(**kw):
        calls.append(kw)
        return SimpleNamespace(prompt_eval_count=prompt_tokens, eval_count=20,
                               message=SimpleNamespace(content=contents[len(calls) - 1]))
    return chat, calls


def test_retry_once_then_success(monkeypatch):
    chat, calls = fake([BAD, GOOD])
    monkeypatch.setattr(llm_client.client, "chat", chat)
    out, logs = llm_client.generate("sys", "user", OutlineOut)
    assert out.scenes[0].source_paragraphs == ["p1"]
    assert [l["status"] for l in logs] == ["retry", "ok"]
    assert calls[0]["format"]["title"] == "OutlineOut"                 # 스키마를 format으로 넘긴다
    assert calls[0]["options"]["num_ctx"] == llm_client.NUM_CTX        # 컨텍스트 길이를 매번 명시한다
    assert "형식 오류" in calls[1]["messages"][-1]["content"]          # 오류를 붙여 다시 요청한다


def test_two_failures_raise_with_logs(monkeypatch):
    chat, calls = fake([BAD, BAD])
    monkeypatch.setattr(llm_client.client, "chat", chat)
    with pytest.raises(llm_client.GenerationError) as e:
        llm_client.generate("sys", "user", OutlineOut)
    assert [l["status"] for l in e.value.logs] == ["retry", "failed"]
    assert len(calls) == 2                                              # 무한 재시도하지 않는다


def test_truncation_risk_flag(monkeypatch):
    chat, _ = fake([GOOD], prompt_tokens=llm_client.NUM_CTX)
    monkeypatch.setattr(llm_client.client, "chat", chat)
    _, logs = llm_client.generate("sys", "user", OutlineOut)
    assert logs[0]["truncation_risk"] is True
