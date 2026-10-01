# schedule.py : 5b단계 수행 일정 배치(설계서 4절). 날짜 계산은 코드가 한다(결정 2).
# LLM은 원고에서 단계별 소요 기간(duration_days)과 반복 주기(interval_days)만 뽑고,
# 이 파일이 매뉴얼 단계 순서대로 "시작일 기준 며칠째"(start_offset_day)를 정한다.
# 실제 날짜로 바꾸는 것은 내보낼 때(CSV, ICS) 사용자가 고른 시작일로 한다(설계서 1절 설계 전제).
from datetime import date, timedelta
from typing import Optional

# 기간 상한 365일: 원고에서 "1년"보다 긴 단계 기간이 나올 일은 드물고, 모델이 잘못 뽑은 큰 값(예: 9999)이
# 일정 전체를 망가뜨리지 않게 막는다. 반복 주기도 같은 이유로 365일에서 자른다.
MAX_DAYS = 365


def clamp_days(value: Optional[int], default: Optional[int] = 1) -> Optional[int]:
    """기간·주기 값을 1~365로 맞춘다. 0이나 음수는 default로 본다(기간 1일 이상, schema.sql CHECK와 C09)."""
    if value is None:
        return default
    try:
        v = int(value)
    except (TypeError, ValueError):
        return default
    if v < 1:
        return default
    return min(v, MAX_DAYS)


def layout(steps: list[dict]) -> list[dict]:
    """매뉴얼 단계 순서대로 일정을 이어 붙인다. 앞 단계가 끝나는 날 다음 단계가 시작한다.
    steps는 [{"seq", "title", "duration_days", "interval_days"}, ...]이며 seq 순서로 정렬해 쓴다.
    반복 작업(interval_days가 있는 단계)도 처음 시작하는 날은 순서대로 정하고, 반복은 ICS의 반복 규칙으로 표현한다.
    돌려주는 값: [{"seq", "step_seq", "title", "start_offset_day", "duration_days", "interval_days"}, ...]"""
    out, offset = [], 0
    for i, st in enumerate(sorted(steps, key=lambda s: s["seq"]), 1):
        duration = clamp_days(st.get("duration_days"), 1)
        out.append({"seq": i, "step_seq": st["seq"], "title": st["title"], "start_offset_day": offset,
                    "duration_days": duration, "interval_days": clamp_days(st.get("interval_days"), None)})
        offset += duration
    return out


def to_dates(start: date, start_offset_day: int, duration_days: int) -> tuple[date, date]:
    """며칠째와 기간을 실제 날짜로 바꾼다. 끝 날짜는 마지막 날(포함)이다. 예: 0일째부터 2일이면 시작일과 다음 날."""
    begin = start + timedelta(days=start_offset_day)
    return begin, begin + timedelta(days=duration_days - 1)
