# projects.py : 프로젝트 만들기, 목록, 상세 API(설계서 6절).
from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import config
from app.api import deps
from app.api.schemas import ProjectDetail, ProjectIn, ProjectListItem, ProjectOut, RunBrief, SettingOut
from app.db import models as m
from app.db.session import get_db

router = APIRouter(prefix="/api/projects", tags=["프로젝트"])


@router.post("", response_model=ProjectOut, status_code=201)
def create_project(body: ProjectIn, db: Session = Depends(get_db)):
    """프로젝트를 만든다. 로그인이 없으므로 주인은 기본 사용자(config.DEFAULT_USER_ID)다."""
    project = m.Project(user_id=config.DEFAULT_USER_ID, title=body.title.strip())
    db.add(project)
    db.commit()           # eager_defaults 덕분에 status, created_at 같은 서버 기본값이 이미 채워져 있다
    return project


@router.get("", response_model=list[ProjectListItem])
def list_projects(q: Optional[str] = None, db: Session = Depends(get_db)):
    """프로젝트 목록. q가 있으면 제목에 그 글자가 든 것만 돌려준다(목록 화면의 검색).
    최근 수정한 프로젝트가 위에 오도록 updated_at 내림차순으로 정렬한다."""
    stmt = select(m.Project).order_by(m.Project.updated_at.desc(), m.Project.id.desc())
    if q and q.strip():
        # LIKE의 특수문자(%와 _)를 이스케이프해 사용자가 입력한 글자 그대로 찾게 한다.
        pattern = "%" + q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        stmt = stmt.where(m.Project.title.like(pattern, escape="\\"))
    projects = db.scalars(stmt).all()
    if not projects:
        return []

    # 프로젝트마다 최근 실행을 따로 조회하면 목록이 길수록 쿼리가 늘어나므로(N+1 문제),
    # 프로젝트별 가장 큰 run id를 한 번에 구한 뒤 그 실행들만 한 번 더 읽는다.
    ids = [p.id for p in projects]
    last_ids = db.execute(select(m.GenerationRun.project_id, func.max(m.GenerationRun.id))
                          .where(m.GenerationRun.project_id.in_(ids))
                          .group_by(m.GenerationRun.project_id)).all()
    runs = {r.id: r for r in db.scalars(select(m.GenerationRun)
                                        .where(m.GenerationRun.id.in_([rid for _, rid in last_ids])))}
    run_by_project = {pid: runs[rid] for pid, rid in last_ids}

    out = []
    for p in projects:
        item = ProjectListItem.model_validate(p)
        run = run_by_project.get(p.id)
        item.latest_run = RunBrief.model_validate(run) if run else None
        out.append(item)
    return out


@router.get("/{project_id}", response_model=ProjectDetail)
def get_project(project_id: int, db: Session = Depends(get_db)):
    """프로젝트 정보와 최신 결과 요약. 화면은 이 응답 하나로 다음 화면(자료 입력, 조건 설정, 결과)을 고른다."""
    p = deps.project_or_404(db, project_id)
    detail = ProjectDetail.model_validate(p)

    src = deps.latest_source(db, project_id)
    if src:
        # 원문 전체는 무거우므로 요약만 넣는다. 원문이 필요하면 GET /sources/latest를 쓴다.
        detail.source = {"id": src.id, "char_count": src.char_count,
                         "paragraph_count": len(src.paragraphs), "file_name": src.file_name}

    setting = deps.latest_setting(db, project_id)
    detail.setting = SettingOut.model_validate(setting) if setting else None

    run = deps.latest_run(db, project_id)
    detail.latest_run = RunBrief.model_validate(run) if run else None

    outline = deps.current_outline(db, project_id)
    if outline:
        detail.outline = {"id": outline.id, "title": outline.title, "scene_count": len(outline.scenes),
                          "run_id": outline.run_id}

    manual = deps.current_manual(db, project_id)
    if manual:
        detail.manual = {"id": manual.id, "title": manual.title, "step_count": len(manual.steps),
                         "run_id": manual.run_id}
    return detail
