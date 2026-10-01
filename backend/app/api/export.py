# export.py : 내보내기 API(설계서 6절). 파일은 서버가 만들고 화면은 내려받기만 한다(설계서 5절).
# GET /api/projects/{id}/export?format=srt|docx|csv|ics|json
import json
import re
from datetime import date
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api import deps
from app.api.schemas import SettingOut
from app.api.views import manual_view, outline_view
from app.db.session import get_db
from app.export import csv_ics, docx_export, srt

router = APIRouter(tags=["내보내기"])

FORMATS = ("srt", "docx", "csv", "ics", "json")


def file_response(content: bytes, filename: str, media_type: str) -> Response:
    """내려받기 응답. 한글 파일 이름은 RFC 5987 형식(filename*=UTF-8'')으로 넣고,
    그 형식을 모르는 옛 프로그램을 위해 영문 대체 이름(filename=)도 함께 넣는다."""
    ascii_name = re.sub(r"[^A-Za-z0-9._-]", "_", filename) or "export"
    disposition = f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"
    return Response(content=content, media_type=media_type, headers={"Content-Disposition": disposition})


def safe_title(title: str) -> str:
    """파일 이름에 쓸 수 없는 글자(Windows 기준 \\ / : * ? " < > |)를 밑줄로 바꾼다. 너무 길면 60자로 자른다."""
    return (re.sub(r'[\\/:*?"<>|\s]+', "_", title).strip("_") or "project")[:60]


def scenes_for_srt(outline) -> list[dict]:
    return [{"duration_sec": sc.duration_sec,
             "cues": [{"start_ms": c.start_ms, "end_ms": c.end_ms, "body": c.body}
                      for c in (sc.narration.cues if sc.narration else [])]}
            for sc in outline.scenes]


@router.get("/api/projects/{project_id}/export")
def export(project_id: int, format: str = Query(..., description="srt, docx, csv, ics, json 중 하나"),
           start_date: Optional[date] = Query(None, description="일정 시작일(csv, ics). 없으면 오늘"),
           kind: str = Query("all", description="docx에 넣을 내용: storyboard, manual, all"),
           db: Session = Depends(get_db)):
    project = deps.project_or_404(db, project_id)
    fmt = format.lower()
    if fmt not in FORMATS:
        raise HTTPException(400, f"지원하지 않는 형식입니다({format}). {', '.join(FORMATS)} 중 하나를 고르세요.")
    base = safe_title(project.title)

    if fmt == "srt":
        outline = deps.current_outline(db, project_id)
        if outline is None:
            raise HTTPException(404, "내보낼 구성안이 없습니다. 먼저 생성해 주세요.")
        text = srt.build_srt(scenes_for_srt(outline))
        if not text:
            raise HTTPException(404, "내보낼 자막이 없습니다. 영상형으로 생성했는지 확인해 주세요.")
        return file_response(srt.to_bytes(text), f"{base}.srt", "application/x-subrip")

    outline = deps.current_outline(db, project_id)
    manual = deps.current_manual(db, project_id)

    if fmt in ("csv", "ics"):
        if manual is None:
            raise HTTPException(404, "내보낼 일정이 없습니다. 매뉴얼형이나 둘 다로 생성해 주세요.")
        data = manual_view(db, manual).model_dump(mode="json")
        start = start_date or date.today()
        if fmt == "csv":
            return file_response(csv_ics.build_csv(data, start), f"{base}_일정.csv", "text/csv; charset=utf-8")
        return file_response(csv_ics.build_ics(data, start, project_id), f"{base}_일정.ics", "text/calendar")

    if fmt == "docx":
        want_story = kind in ("all", "storyboard")
        want_manual = kind in ("all", "manual")
        o = outline_view(db, outline).model_dump(mode="json") if (outline and want_story) else None
        mv = manual_view(db, manual).model_dump(mode="json") if (manual and want_manual) else None
        if o is None and mv is None:
            raise HTTPException(404, "내보낼 결과가 없습니다. 먼저 생성해 주세요.")
        return file_response(docx_export.build_docx(project.title, o, mv), f"{base}.docx",
                             "application/vnd.openxmlformats-officedocument.wordprocessingml.document")

    # json: 프로젝트의 현재 결과 전체. 다른 도구로 옮기거나 결과보고서에 붙일 때 쓴다.
    setting = deps.latest_setting(db, project_id)
    payload = {"project": {"id": project.id, "title": project.title, "status": project.status},
               "setting": SettingOut.model_validate(setting).model_dump(mode="json") if setting else None,
               "outline": outline_view(db, outline).model_dump(mode="json") if outline else None,
               "manual": manual_view(db, manual).model_dump(mode="json") if manual else None}
    body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    return file_response(body, f"{base}.json", "application/json")
