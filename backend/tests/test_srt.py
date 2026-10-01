# SRT 내보내기 테스트(DB 없이). 장면 기준 시간을 영상 전체 기준으로 누적하는지 확인한다.
from app.export import srt


def test_timestamp_format():
    assert srt.ms_to_timestamp(0) == "00:00:00,000"
    assert srt.ms_to_timestamp(3723004) == "01:02:03,004"


def test_build_srt_accumulates_scene_offsets():
    scenes = [
        {"duration_sec": 30, "cues": [{"start_ms": 0, "end_ms": 4000, "body": "드릴을 켜기 전에\n배터리 확인"},
                                      {"start_ms": 4000, "end_ms": 30000, "body": "딸깍 소리"}]},
        {"duration_sec": 20, "cues": []},                          # 내레이션 없는 장면도 시간은 차지한다
        {"duration_sec": 30, "cues": [{"start_ms": 0, "end_ms": 30000, "body": "보안경 착용"}]},
    ]
    text = srt.build_srt(scenes)
    blocks = text.split("\r\n\r\n")
    assert blocks[0] == "1\r\n00:00:00,000 --> 00:00:04,000\r\n드릴을 켜기 전에\r\n배터리 확인"
    assert blocks[2].startswith("3\r\n00:00:50,000 --> 00:01:20,000")  # 30초 + 20초 뒤에서 시작
    assert srt.to_bytes(text).startswith(b"\xef\xbb\xbf")             # BOM이 붙은 UTF-8
