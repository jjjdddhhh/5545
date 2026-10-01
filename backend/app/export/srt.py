# srt.py : 자막을 SRT 파일로 만든다(설계서 4절 5a, 11절 "SRT는 표준 라이브러리로 만든다").
# DB의 자막 시간은 장면 시작 기준이므로, 내보낼 때 앞 장면들의 시간을 더해 영상 전체 기준으로 바꾼다.
#
# SRT 형식(한 자막):
#   1
#   00:00:00,000 --> 00:00:04,250
#   드릴을 켜기 전에
#   배터리가 끝까지
#   (빈 줄)
#
# 줄바꿈은 CRLF(\r\n), 인코딩은 BOM이 붙은 UTF-8로 쓴다. 한국어 Windows의 영상 편집기와 플레이어 가운데
# BOM이 없으면 한글을 CP949로 읽어 글자가 깨지는 것이 있고, SRT의 원래 형식이 CRLF이기 때문이다.
# BOM은 bytes로 바꿀 때(to_bytes) 붙인다.


def ms_to_timestamp(ms: int) -> str:
    """밀리초를 SRT 시각(시:분:초,밀리초)으로 바꾼다. 예: 3723004 -> 01:02:03,004"""
    ms = max(0, int(ms))
    h, rest = divmod(ms, 3_600_000)
    mnt, rest = divmod(rest, 60_000)
    s, milli = divmod(rest, 1000)
    return f"{h:02d}:{mnt:02d}:{s:02d},{milli:03d}"


def build_srt(scenes: list[dict]) -> str:
    """scenes는 seq 순서로 정렬된 [{"duration_sec": 30, "cues": [{"start_ms", "end_ms", "body"}, ...]}, ...]이다.
    내레이션이 없는 장면도 시간은 차지하므로 다음 장면의 시작 시각을 그만큼 뒤로 민다."""
    blocks = []
    offset_ms = 0
    index = 1
    for sc in scenes:
        for cue in sorted(sc.get("cues") or [], key=lambda c: c["start_ms"]):
            start = offset_ms + cue["start_ms"]
            end = offset_ms + cue["end_ms"]
            body = "\r\n".join(line for line in cue["body"].split("\n") if line.strip())
            blocks.append(f"{index}\r\n{ms_to_timestamp(start)} --> {ms_to_timestamp(end)}\r\n{body}\r\n")
            index += 1
        offset_ms += int(sc["duration_sec"]) * 1000
    return "\r\n".join(blocks)


def to_bytes(srt_text: str) -> bytes:
    return srt_text.encode("utf-8-sig")
