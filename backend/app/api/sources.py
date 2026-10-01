# sources.py : 원고 입력과 문단 고치기 API(설계서 6절, 4절 텍스트 변환 상세).
# 정제 규칙은 모두 text_cleaner에 있고, 이 파일은 받은 글이나 파일을 text_cleaner에 넘겨 결과를 저장만 한다.
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api import deps
from app.api.schemas import ParagraphsIn, SourceOut
from app.db import models as m
from app.db.session import get_db
from app.pipeline import text_cleaner as tc

router = APIRouter(tags=["원고"])

ALLOWED_EXT = {".txt", ".md", ".docx", ".pdf", ".hwpx", ".hwp"}  # .hwp는 받아서 안내 메시지(400)를 돌려주려고 넣었다
# 20MB 상한: 교육 원고 문서로는 충분히 크고(텍스트 위주 PDF 수백 쪽), 실수로 동영상 같은 큰 파일을
# 올렸을 때 서버 메모리를 다 쓰지 않게 막는 값이다.
MAX_UPLOAD_BYTES = 20 * 1024 * 1024


def paragraph_stats(paragraphs: list[dict]) -> dict:
    """문단 목록만으로 다시 셀 수 있는 통계. 업로드 직후가 아닌 조회 응답의 stats로 쓴다."""
    return {"paragraphs": len(paragraphs),
            "headings": sum(p["kind"] == "heading" for p in paragraphs),
            "tables": sum(p["kind"] == "table" for p in paragraphs),
            "clean_chars": sum(len(p["text"]) for p in paragraphs)}


def to_out(src: m.SourceDocument, stats: dict | None = None, warnings: list[str] | None = None) -> SourceOut:
    out = SourceOut.model_validate(src)
    out.stats = stats if stats is not None else paragraph_stats(src.paragraphs)
    out.warnings = warnings or []
    return out


@router.post("/api/projects/{project_id}/sources", response_model=SourceOut, status_code=201)
async def upload_source(project_id: int,
                        text: Optional[str] = Form(default=None),
                        file: Optional[UploadFile] = File(default=None),
                        db: Session = Depends(get_db)):
    """붙여넣은 글(text) 또는 파일(file)을 받아 정제하고 저장한다. 둘 다 오면 파일을 쓴다.
    응답은 원문, 정제본, 문단 목록, 정제 통계, 경고를 담은 비교 미리보기다."""
    project = deps.project_or_404(db, project_id)

    if file is not None and file.filename:
        # ---------- 파일 ----------
        ext = Path(file.filename).suffix.lower()
        if ext not in ALLOWED_EXT:
            raise HTTPException(400, f"지원하지 않는 형식입니다({ext}). txt, docx, pdf, hwpx 파일을 올려 주세요.")
        data = await file.read()
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(400, "파일이 20MB를 넘습니다. 원고 부분만 나눠서 올려 주세요.")
        # text_cleaner.extract_pages는 경로를 받으므로 임시 파일에 쓴다. 확장자로 형식을 고르므로 suffix를 유지한다.
        # Windows에서는 열려 있는 임시 파일을 다른 코드가 다시 열 수 없으므로, delete=False로 만들고 닫은 뒤 읽고 지운다.
        tmp = tempfile.NamedTemporaryFile(suffix=ext, delete=False)
        try:
            tmp.write(data)
            tmp.close()
            try:
                pages = tc.extract_pages(tmp.name)
            except tc.UnsupportedFormat as exc:
                # hwp 안내("hwpx, docx, pdf 중 하나로 저장해 올려 주세요")가 여기로 온다.
                raise HTTPException(400, str(exc))
            except Exception as exc:  # 깨진 docx나 암호 걸린 pdf처럼 라이브러리가 읽지 못한 경우
                raise HTTPException(400, f"파일을 읽지 못했습니다. 파일이 손상되었거나 암호가 걸려 있을 수 있습니다. ({exc})")
        finally:
            Path(tmp.name).unlink(missing_ok=True)
        result = tc.clean(pages, is_pdf=(ext == ".pdf"))
        raw_text = "\n\n".join(pages)   # 원문 보기에서 쪽 경계를 빈 줄로 구분해 보여 준다
        source_type, file_name = "file", file.filename[:255]  # file_name VARCHAR(255)
    elif text is not None and text.strip():
        # ---------- 붙여넣은 글 ----------
        result = tc.clean_pasted(text)
        raw_text, source_type, file_name = text, "paste", None
    else:
        raise HTTPException(400, "원고 글을 붙여넣거나 파일을 올려 주세요.")

    if not result.paragraphs:
        # 스캔 PDF처럼 글자를 하나도 뽑지 못하면 저장해도 생성할 수 없으므로 경고와 함께 거절한다.
        raise HTTPException(400, " ".join(result.warnings) or "원고에서 글자를 뽑지 못했습니다.")

    src = m.SourceDocument(project_id=project.id, source_type=source_type, file_name=file_name,
                           raw_text=raw_text, clean_text=result.clean_text, paragraphs=result.paragraphs,
                           char_count=len(result.clean_text))
    db.add(src)
    db.commit()
    return to_out(src, result.stats, result.warnings)


@router.get("/api/projects/{project_id}/sources/latest", response_model=SourceOut)
def get_latest_source(project_id: int, db: Session = Depends(get_db)):
    """자료 입력 화면을 다시 열었을 때 마지막 원고를 보여 주려고 둔 조회 API(설계서 6절 표에 더한 것)."""
    deps.project_or_404(db, project_id)
    src = deps.latest_source(db, project_id)
    if src is None:
        raise HTTPException(404, "아직 원고가 없습니다.")
    return to_out(src)


@router.put("/api/sources/{source_id}/paragraphs", response_model=SourceOut)
def save_paragraphs(source_id: int, body: ParagraphsIn, db: Session = Depends(get_db)):
    """사용자가 미리보기에서 합치거나 나눈 문단을 저장하고 번호를 p1부터 다시 매긴다.

    이미 생성 실행이 이 원고를 썼다면 원래 행을 고치지 않고 새 원고 행을 만든다.
    번호를 다시 매기면 이전 실행의 장면이 가리키던 근거 문단 번호(p3 등)가 다른 글을 가리키게 되어,
    이전 결과의 근거 추적(검수 C03)이 깨지기 때문이다. 응답의 id가 바뀌었는지로 화면이 이를 알 수 있다."""
    src = deps.get_or_404(db, m.SourceDocument, source_id, "원고")

    # 번호 다시 매기기. 앞뒤 공백을 지우고, 공백만 남은 문단은 버린다.
    paragraphs = []
    for p in body.paragraphs:
        text = p.text.strip()
        if text:
            paragraphs.append({"id": f"p{len(paragraphs) + 1}", "kind": p.kind, "text": text})
    if not paragraphs:
        raise HTTPException(400, "빈 문단만 남았습니다. 문단을 하나 이상 남겨 주세요.")
    clean_text = "\n\n".join(p["text"] for p in paragraphs)  # text_cleaner.clean과 같은 방식으로 정제본을 만든다

    used = db.scalar(select(m.GenerationRun.id).where(m.GenerationRun.source_id == src.id).limit(1))
    if used is not None:
        src = m.SourceDocument(project_id=src.project_id, source_type=src.source_type, file_name=src.file_name,
                               raw_text=src.raw_text, clean_text=clean_text, paragraphs=paragraphs,
                               char_count=len(clean_text))
        db.add(src)
    else:
        src.paragraphs = paragraphs   # JSON 컬럼은 새 리스트를 대입해야 변경이 감지된다
        src.clean_text = clean_text
        src.char_count = len(clean_text)
    db.commit()
    return to_out(src)
