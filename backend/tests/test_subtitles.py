# 자막 분할과 타이밍 테스트(DB 없이). 설계서 4절: 한 줄 16자, 최대 2줄, 단어 중간에서 끊지 않음, 글자 수 비례 배분.
from app.pipeline import subtitles as st

NARR = ("드릴을 켜기 전에 배터리가 끝까지 끼워졌는지 확인합니다. 딸깍 소리가 나야 합니다. "
        "비트는 척에 깊이 넣고 척 키로 세 군데를 고르게 조여 주세요.")


def test_lines_respect_limits_and_word_boundaries():
    cues = st.split_subtitles(NARR, 16, 2)
    words = set(NARR.replace(".", " ").split())
    for cue in cues:
        lines = cue.split("\n")
        assert 1 <= len(lines) <= 2
        assert all(len(line) <= 16 for line in lines)
        for line in lines:                                   # 줄을 이루는 단어가 모두 원래 단어다(중간에서 안 끊음)
            assert all(w.rstrip(".") in words for w in line.split(" "))
    joined = " ".join(c.replace("\n", " ") for c in cues)
    assert joined == NARR                                    # 글자가 빠지거나 더해지지 않는다


def test_cue_does_not_span_sentences_and_lines_are_balanced():
    cues = st.split_subtitles(NARR, 16, 2)
    assert cues[0].endswith("확인합니다.")                     # 첫 문장이 끝나는 곳에서 큐가 끝난다
    assert cues[0] == "드릴을 켜기 전에 배터리가\n끝까지 끼워졌는지 확인합니다."
    assert cues[1] == "딸깍 소리가 나야 합니다."
    assert cues[2:] == ["비트는 척에 깊이\n넣고 척 키로", "세 군데를 고르게\n조여 주세요."]  # 한 단어 꼬리 큐가 없다


def test_two_line_cue_is_balanced():
    # 앞에서부터 채우면 14자+6자지만, 두 줄 차이가 가장 작은 11자+9자로 끊는다
    assert st.split_subtitles("보안경과 장갑은 작업 내내 착용합니다.", 16, 2) == ["보안경과 장갑은 작업\n내내 착용합니다."]
    assert st.split_subtitles("가나다라마바사아자차카 타파", 16, 2) == ["가나다라마바사아자차카 타파"]  # 한 줄이면 그대로


def test_long_word_and_no_period():
    cues = st.split_subtitles("가" * 40, 16, 2)
    assert cues == ["가" * 16, "가" * 16 + "\n" + "가" * 8]   # 한 줄보다 긴 단어만 글자 단위로 자르고, 큐 길이는 고르게
    assert len(st.split_subtitles("배터리를 끼웁니다 비트를 넣어요 척을 조입니다", 16, 2)) == 3  # 마침표 없이 어미로 자른다
    assert st.split_subtitles("   ") == []


def test_timing_proportional_and_exact_total():
    bodies = ["가나다라", "가나", "가나다라마바"]                # 글자 수 4:2:6
    t = st.time_cues(bodies, 12000)
    assert t == [(0, 4000), (4000, 6000), (6000, 12000)]
    t = st.time_cues(["가"] * 7, 10000)
    assert t[0][0] == 0 and t[-1][1] == 10000
    assert all(e > s for s, e in t) and all(t[i][1] == t[i + 1][0] for i in range(6))  # 겹치거나 비지 않는다


def test_timing_never_zero_length():
    t = st.time_cues(["가" * 100, "나"], 3)                    # 극단적으로 짧은 장면에서도 끝이 시작보다 뒤
    assert t[-1][1] == 3 and all(e > s for s, e in t)


def test_build_cues_rows():
    rows = st.build_cues(NARR, 30)
    assert rows[0]["seq"] == 1 and rows[0]["start_ms"] == 0 and rows[-1]["end_ms"] == 30000
    assert all(len(r["body"]) <= 100 for r in rows)          # subtitle_cue.body VARCHAR(100)
