# docx_export.py : 스토리보드와 매뉴얼을 Word(DOCX) 문서로 만든다(설계서 2절 ⑤).
# 입력은 OutlineView, ManualView의 model_dump() 딕셔너리다. 둘 중 있는 것만 문서에 넣는다.
# 호롱불의 스토리보드 양식(설계서 14절 A3)을 받으면 표의 열 구성과 순서를 그 양식에 맞춰 바꾼다.
import io
from typing import Optional

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.oxml.ns import qn
from docx.shared import Cm, Pt

# 한글 글꼴. Word는 동아시아 글자에 따로 지정한 글꼴(eastAsia)을 쓰므로 그 자리에도 넣어야 한글이 이 글꼴로 나온다.
# 맑은 고딕은 Windows에 기본으로 들어 있다.
FONT = "맑은 고딕"
SEVERITY_LABEL = {"info": "참고", "warning": "주의", "danger": "위험"}
DIFFICULTY_LABEL = {"beginner": "초급", "intermediate": "중급", "advanced": "고급"}


def _set_font(doc: Document) -> None:
    style = doc.styles["Normal"]
    style.font.name = FONT
    style.font.size = Pt(10)
    style.element.rPr.rFonts.set(qn("w:eastAsia"), FONT)


def _fmt_time(sec: int) -> str:
    """초를 분:초로. 예: 90 -> 1:30"""
    return f"{sec // 60}:{sec % 60:02d}"


def _storyboard(doc: Document, outline: dict) -> None:
    o = outline["outline"]
    doc.add_heading(f"스토리보드 · {o['title']}", level=1)
    doc.add_paragraph(o["summary"])
    if o.get("learning_objectives"):
        doc.add_paragraph("학습목표", style="Heading 3")
        for obj in o["learning_objectives"]:
            doc.add_paragraph(obj, style="List Bullet")
    doc.add_paragraph(f"전체 길이 {_fmt_time(outline['total_sec'])}, 장면 {len(outline['scenes'])}개")

    # 표 열: 장면, 시간, 화면 설명, 시각자료, 화면 텍스트, 내레이션. 가로가 넓어야 읽기 쉬워 이 구역은 가로 방향으로 둔다.
    headers = ["장면", "시간", "화면 설명", "시각자료 제안", "화면 텍스트", "내레이션"]
    widths = [Cm(3.0), Cm(2.0), Cm(5.5), Cm(4.0), Cm(3.5), Cm(7.5)]
    table = doc.add_table(rows=1, cols=len(headers))
    table.style = "Table Grid"
    for cell, h, wd in zip(table.rows[0].cells, headers, widths):
        cell.text = h
        cell.width = wd
        for r in cell.paragraphs[0].runs:
            r.bold = True
    for sc in outline["scenes"]:
        start, end = sc["start_sec"], sc["start_sec"] + sc["duration_sec"]
        values = [f"{sc['seq']}. {sc['title']}\n(근거 {', '.join(sc['source_paragraphs']) or '없음'})",
                  f"{_fmt_time(start)}~{_fmt_time(end)}\n({sc['duration_sec']}초)",
                  sc.get("screen_description") or "", sc.get("visual_suggestion") or "",
                  sc.get("on_screen_text") or "", (sc.get("narration") or {}).get("body", "")]
        row = table.add_row().cells
        for cell, v, wd in zip(row, values, widths):
            cell.text = v
            cell.width = wd


def _manual(doc: Document, manual: dict) -> None:
    mi = manual["manual"]
    doc.add_heading(f"매뉴얼 · {mi['title']}", level=1)
    doc.add_paragraph(f"대상: {mi['audience']} / 난이도: {DIFFICULTY_LABEL.get(mi['difficulty'], mi['difficulty'])}")
    if mi.get("intro"):
        doc.add_paragraph(mi["intro"])

    doc.add_heading("작업 단계", level=2)
    for st in manual["steps"]:
        doc.add_paragraph(f"{st['seq']}. {st['title']}", style="Heading 3")
        doc.add_paragraph(st["instruction"])
        if st.get("tip"):
            doc.add_paragraph("도움말: " + st["tip"])

    if manual["cautions"]:
        doc.add_heading("주의사항", level=2)
        for c in manual["cautions"]:
            doc.add_paragraph(f"[{SEVERITY_LABEL.get(c['severity'], c['severity'])}] {c['body']}", style="List Bullet")

    if manual["schedule"]:
        doc.add_heading("수행 일정", level=2)
        table = doc.add_table(rows=1, cols=4)
        table.style = "Table Grid"
        for cell, h in zip(table.rows[0].cells, ["순서", "일정", "시작(며칠째)", "기간과 반복"]):
            cell.text = h
        for it in manual["schedule"]:
            span = f"{it['duration_days']}일" + (f", {it['interval_days']}일마다 반복" if it.get("interval_days") else "")
            row = table.add_row().cells
            row[0].text, row[1].text = str(it["seq"]), it["title"]
            row[2].text, row[3].text = f"{it['start_offset_day'] + 1}일째", span


def build_docx(project_title: str, outline: Optional[dict], manual: Optional[dict]) -> bytes:
    doc = Document()
    _set_font(doc)
    doc.add_heading(project_title, level=0)
    if outline:
        sec = doc.sections[0]
        sec.orientation = WD_ORIENT.LANDSCAPE                     # 스토리보드 표는 가로 방향에서 읽기 쉽다
        sec.page_width, sec.page_height = sec.page_height, sec.page_width
        sec.left_margin = sec.right_margin = Cm(1.5)
        _storyboard(doc, outline)
    if manual:
        if outline:
            doc.add_page_break()
        _manual(doc, manual)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
