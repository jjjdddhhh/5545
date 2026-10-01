# 검수 함수 테스트(DB 없이). 설계서 10절 C01~C12 가운데 순수 계산 항목과 저장 정책을 확인한다.
from app.pipeline import checks as ck
from app.pipeline import review
from app.pipeline.subtitles import build_cues

PARAS = [{"id": "p1", "kind": "body", "text": "보안경과 장갑을 반드시 착용한다. 딸깍 소리가 나야 한다."},
         {"id": "p2", "kind": "body", "text": "헐렁한 장갑은 회전부에 말려 들어갈 수 있으므로 쓰지 않는다. 100% 충전한다."}]
TERMS = ["반드시", "말려 들어갈", "않는다"]


def test_keywords_ignore_spacing():
    assert ck.check_keywords(["보호 장갑", "배터리"], "보호장갑을 끼고 배터리를 본다").result == "pass"
    r = ck.check_keywords(["보안경", "척 키"], "보안경을 쓴다")
    assert r.result == "warn" and r.data["missing"] == ["척 키"]


def test_subtitle_lines_and_timing():
    cues = build_cues("드릴을 켜기 전에 배터리가 끝까지 끼워졌는지 확인합니다.", 10)
    assert ck.check_subtitle_lines(cues, 16).result == "pass"
    assert ck.check_subtitle_timing(cues, 10).result == "pass"
    assert ck.check_subtitle_lines([{"seq": 1, "body": "가\n나\n다"}], 16).result == "fail"
    assert ck.check_subtitle_lines([{"seq": 1, "body": "가" * 17}], 16).result == "fail"
    overlap = [{"seq": 1, "start_ms": 0, "end_ms": 6000, "body": "a"}, {"seq": 2, "start_ms": 5000, "end_ms": 10000, "body": "b"}]
    assert "겹칩니다" in ck.check_subtitle_timing(overlap, 10).message
    short = [{"seq": 1, "start_ms": 0, "end_ms": 9000, "body": "a"}]
    assert "장면 시간" in ck.check_subtitle_timing(short, 10).message


def test_warning_sentences_and_reflection():
    found = ck.warning_sentences(PARAS, TERMS)
    assert [w["paragraph"] for w in found] == ["p1", "p2"]
    r = ck.check_warnings(PARAS, ["헐렁한 장갑은 회전부에 말려 들어가므로 금지한다."], TERMS)
    assert r.result == "warn" and [w["paragraph"] for w in r.data["missing"]] == ["p1"]  # 장갑 문장은 반영됨
    r = ck.check_warnings(PARAS, ["보안경과 장갑 착용", "헐렁한 장갑은 회전부에 말려 들어감"], TERMS)
    assert r.result == "pass"
    # 단어 하나만 우연히 겹치면 반영된 것으로 보지 않는다
    assert ck.check_warnings(PARAS[:1], ["장갑 보관 방법"], TERMS).result == "warn"


def test_hype_terms_and_source_exemption():
    terms = ["완벽하게", "100%"]
    src = "\n".join(p["text"] for p in PARAS)
    assert ck.check_hype("완벽하게 조인다", terms, src, "scene", 1).result == "warn"
    assert ck.check_hype("100% 충전한 뒤 쓴다", terms, src, "scene", 1).result == "pass"  # 원고에 있는 표현


def test_load_terms_files_have_drafts():
    assert "반드시" in ck.load_terms("warning_terms.txt")
    assert "무조건" in ck.load_terms("hype_terms.txt")
    assert all(not t.startswith("#") for t in ck.load_terms("hype_terms.txt"))


def _input(**kw):
    narr = "드릴을 켜기 전에 배터리가 끝까지 끼워졌는지 확인합니다. 보안경과 장갑을 반드시 착용합니다."
    scene = {"id": 1, "seq": 1, "title": "작업 전 점검", "key_point": "배터리와 보호구를 확인한다",
             "source_paragraphs": ["p1"], "screen_description": "손을 가까이 보여 준다", "visual_suggestion": "클로즈업",
             "on_screen_text": "배터리 확인", "duration_sec": 10, "char_budget": len(narr.replace(" ", "")),
             "narration": {"id": 5, "body": narr}, "cues": build_cues(narr, 10), "cautions": []}
    manual = {"id": 9, "title": "매뉴얼", "intro": "신입 사원용 매뉴얼이다.",
              "steps": [{"id": 3, "seq": 1, "title": "보호구", "instruction": "보안경과 장갑을 착용한다.", "tip": None,
                         "source_paragraphs": ["p1"]}],
              "cautions": [{"body": "보안경과 장갑을 반드시 착용한다."},
                           {"body": "헐렁한 장갑은 회전부에 말려 들어갈 수 있어 쓰지 않는다."}],
              "schedule": [{"seq": 1, "step_seq": 1, "title": "보호구", "start_offset_day": 0, "duration_days": 1}]}
    base = dict(content_type="both", language="ko", keywords=["보안경"], subtitle_max_chars=16, paragraphs=PARAS,
                expected_scene_count=1, outline={"title": "드릴 안전", "summary": "안전하게 쓰는 법을 익힌다.",
                                                 "learning_objectives": ["점검할 수 있다"]},
                scenes=[scene], manual=manual)
    base.update(kw)
    return ck.CheckInput(**base)


def test_run_checks_all_pass_on_good_input():
    results = ck.run_checks(_input())
    bad = [(r.code, r.message) for r in results if r.result != "pass"]
    assert bad == []
    assert {r.code for r in results} == {f"C{i:02d}" for i in range(2, 13)}   # C01은 생성 단계 결과라 여기 없다


def test_run_checks_detects_problems():
    inp = _input(expected_scene_count=3, keywords=["척 키"])
    inp.scenes[0]["narration"]["body"] = "완벽하게 확인합니다."
    inp.manual["steps"][0]["instruction"] = "10분 동안 착용한다."
    codes = {r.code for r in ck.run_checks(inp) if r.result != "pass"}
    assert {"C02", "C04", "C05", "C08", "C12"} <= codes


def test_storage_policy():
    fail = ck.CheckResult("C04", "fail", "길다", "narration", 1)
    assert review.final_result(fail, retried=True, fixed=False) == ("warn", "1회 다시 요청했지만 통과하지 못했습니다. 길다")
    assert review.final_result(fail, retried=False, fixed=False)[0] == "warn"
    assert review.final_result(ck.CheckResult("C01", "fail", "x"), False, False)[0] == "fail"   # 생성 실패만 fail
    ok = ck.CheckResult("C06", "pass", "ok")
    assert review.final_result(ok, False, True)[1].startswith("자동으로 고쳤습니다")
