# smoke_ollama.py 테스트(DB 없이). 실제 모델 대신 가짜 Ollama로 표가 만들어지는지만 확인한다.
from pathlib import Path

from app.llm import llm_client
from scripts import smoke_ollama
from tests.fake_llm import FakeOllama


def test_smoke_runs_whole_pipeline_with_fake(monkeypatch, capsys):
    fake = FakeOllama()
    monkeypatch.setattr(llm_client.client, "chat", fake)
    text = Path(smoke_ollama.DEFAULT_SOURCE).read_text(encoding="utf-8")
    res = smoke_ollama.run_smoke(text, "both", 150)
    assert len(res["scenes"]) == 5 and res["manual"]["steps"] and not res["errors"]
    table = {r["stage"]: r for r in smoke_ollama.stage_table(res)}
    assert table["장면 상세"]["calls"] == 5 and table["장면 상세"]["json_ok"] == 5
    assert table["내레이션"]["calls"] == 5 and table["구조화·구성안"]["truncation"] is False
    smoke_ollama.print_report("가짜모델", res)
    out = capsys.readouterr().out
    assert "| 단계 | 호출 | JSON 성공" in out and "장면당 생성 시간" in out


def test_sample_source_shape():
    from app.pipeline import text_cleaner
    text = Path(smoke_ollama.DEFAULT_SOURCE).read_text(encoding="utf-8")
    assert 1300 <= len(text) <= 1700                              # 1,500자 안팎
    r = text_cleaner.clean_pasted(text)
    assert r.stats["tables"] >= 1 and r.stats["headings"] >= 5   # 제목, 목록, 표가 섞인 형태
