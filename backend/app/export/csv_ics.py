# csv_ics.py : 수행 일정을 CSV와 ICS(캘린더) 파일로 만든다(설계서 2절 ⑤, 4절 5b).
# 입력은 ManualView.model_dump() 모양의 딕셔너리다. DB를 모르므로 단위 테스트가 쉽다.
# 일정은 "시작일 기준 며칠째"로 저장되어 있으므로, 사용자가 고른 시작일(start)로 실제 날짜를 계산한다.
import csv
import io
from datetime import date, datetime, timedelta, timezone

from icalendar import Calendar, Event, vRecur

from app import config
from app.pipeline.schedule import to_dates

CSV_HEADER = ["순서", "일정", "시작(며칠째)", "기간(일)", "반복 주기(일)", "시작일", "종료일", "매뉴얼 단계", "메모"]


def build_csv(manual: dict, start: date) -> bytes:
    """일정 표. 엑셀에서 한글이 깨지지 않도록 BOM이 붙은 UTF-8로 쓴다(엑셀은 BOM이 없으면 CP949로 읽는다).
    "며칠째"는 사람이 읽기 쉽게 1부터 센다(저장값 0은 "1일째")."""
    steps = {s["id"]: s for s in manual["steps"]}
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(CSV_HEADER)
    for it in manual["schedule"]:
        begin, end = to_dates(start, it["start_offset_day"], it["duration_days"])
        step = steps.get(it.get("manual_step_id"))
        w.writerow([it["seq"], it["title"], it["start_offset_day"] + 1, it["duration_days"],
                    it.get("interval_days") or "", begin.isoformat(), end.isoformat(),
                    f"{step['seq']}. {step['title']}" if step else "", it.get("note") or ""])
    return buf.getvalue().encode("utf-8-sig")


def build_ics(manual: dict, start: date, project_id: int) -> bytes:
    """캘린더 파일. 일정 하나가 하루 종일 일정(VEVENT) 하나가 된다.
    - DTEND는 끝나는 날의 다음 날이다(iCalendar 규칙: 종일 일정의 끝은 포함하지 않는다).
    - 반복 작업이면 RRULE(FREQ=DAILY, INTERVAL=주기)로 반복하고, 끝없이 이어지지 않게 config.ICS_REPEAT_COUNT회로 끊는다.
    - UID는 프로젝트, 매뉴얼, 일정 id로 만들어, 같은 파일을 다시 불러오면 캘린더 앱이 새로 더하지 않고 바꾼다."""
    steps = {s["id"]: s for s in manual["steps"]}
    cal = Calendar()
    cal.add("prodid", "-//content-ai-platform//schedule//KO")
    cal.add("version", "2.0")
    cal.add("x-wr-calname", manual["manual"]["title"])
    stamp = datetime.now(timezone.utc)
    for it in manual["schedule"]:
        begin = start + timedelta(days=it["start_offset_day"])
        ev = Event()
        ev.add("uid", f"p{project_id}-m{manual['manual']['id']}-s{it['id']}@content-ai.local")
        ev.add("dtstamp", stamp)
        ev.add("summary", it["title"])
        ev.add("dtstart", begin)
        ev.add("dtend", begin + timedelta(days=it["duration_days"]))
        step = steps.get(it.get("manual_step_id"))
        desc = []
        if step:
            desc.append(step["instruction"])
            if step.get("tip"):
                desc.append("도움말: " + step["tip"])
        if it.get("note"):
            desc.append("메모: " + it["note"])
        if desc:
            ev.add("description", "\n".join(desc))
        if it.get("interval_days"):
            ev.add("rrule", vRecur({"FREQ": "DAILY", "INTERVAL": it["interval_days"],
                                    "COUNT": config.ICS_REPEAT_COUNT}))
        cal.add_component(ev)
    return cal.to_ical()
