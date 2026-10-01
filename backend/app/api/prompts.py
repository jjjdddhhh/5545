# prompts.py : 단계별 프롬프트 템플릿 조회와 새 버전 저장 API(설계서 6절, 9절).
# 템플릿을 고치면 기존 행을 바꾸지 않고 새 버전을 만든다. 실행 로그(agent_step_log.prompt_template_id)에
# 어떤 버전을 썼는지 남으므로, 결과 차이를 버전별로 비교할 수 있다.
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.api.schemas import PromptIn, PromptSaved, PromptVersion, PromptView
from app.db import models as m
from app.db.session import get_db
from app.llm.prompt_store import active_prompt, file_prompt, placeholders
from app.llm.schemas import STAGE_MODELS

router = APIRouter(prefix="/api/prompts", tags=["프롬프트"])


def _stage_or_404(stage: str) -> str:
    if stage not in STAGE_MODELS:
        raise HTTPException(404, f"프롬프트 단계는 {', '.join(STAGE_MODELS)} 중 하나입니다. (quiz는 선택 기능이라 아직 없습니다.)")
    return stage


def _view(db: Session, stage: str) -> PromptView:
    p = active_prompt(db, stage)
    rows = db.scalars(select(m.PromptTemplate).where(m.PromptTemplate.stage == stage)
                      .order_by(m.PromptTemplate.version)).all()
    versions = [PromptVersion(id=r.id, version=r.version, is_active=r.is_active, created_at=r.created_at) for r in rows]
    if not rows:   # DB에 아직 없으면 파일 원문을 버전 1로 보여 준다
        versions = [PromptVersion(id=None, version=1, is_active=True)]
    return PromptView(stage=stage, source="db" if p.template_id else "file", version=p.version,
                      system_prompt=p.system, user_template=p.user,
                      output_schema=STAGE_MODELS[stage].model_json_schema(),
                      placeholders=sorted(placeholders(p.system) | placeholders(p.user)), versions=versions)


@router.get("/{stage}", response_model=PromptView)
def get_prompt(stage: str, db: Session = Depends(get_db)):
    """현재 쓰는(활성) 템플릿과 버전 목록을 돌려준다."""
    return _view(db, _stage_or_404(stage))


@router.put("/{stage}", response_model=PromptSaved)
def put_prompt(stage: str, body: PromptIn, db: Session = Depends(get_db)):
    """템플릿을 새 버전으로 저장하고 활성으로 바꾼다. 출력 스키마는 코드의 Pydantic 모델에서 만들어 함께 저장한다
    (사용자가 스키마를 고치면 코드의 검증과 어긋나므로 템플릿 글만 고칠 수 있게 했다).
    DB에 버전이 하나도 없으면 파일 원문을 버전 1로 먼저 넣고 새 글을 버전 2로 넣어, 처음 원문도 이력에 남긴다."""
    _stage_or_404(stage)
    schema = STAGE_MODELS[stage].model_json_schema()
    latest = db.scalar(select(func.max(m.PromptTemplate.version)).where(m.PromptTemplate.stage == stage))
    if latest is None:
        f = file_prompt(stage)
        db.add(m.PromptTemplate(stage=stage, version=1, system_prompt=f.system, user_template=f.user,
                                output_schema=schema, is_active=False))
        latest = 1
    db.execute(update(m.PromptTemplate).where(m.PromptTemplate.stage == stage).values(is_active=False))
    db.add(m.PromptTemplate(stage=stage, version=latest + 1, system_prompt=body.system_prompt.strip(),
                            user_template=body.user_template.strip(), output_schema=schema, is_active=True))
    db.commit()

    # 버전 1(파일 원문)에 있던 변수가 빠졌으면 알려 준다. 막지는 않는다(톤처럼 일부러 뺄 수도 있기 때문이다).
    base = file_prompt(stage)
    missing = (placeholders(base.system) | placeholders(base.user)) - \
        (placeholders(body.system_prompt) | placeholders(body.user_template))
    warnings = [f"원래 템플릿에 있던 변수 {{{name}}}가 빠졌습니다. 그 값은 모델에게 전달되지 않습니다." for name in sorted(missing)]
    return PromptSaved(**_view(db, stage).model_dump(), warnings=warnings)


@router.post("/{stage}/versions/{version}/activate", response_model=PromptView)
def activate_version(stage: str, version: int, db: Session = Depends(get_db)):
    """예전 버전으로 되돌린다. 행을 새로 만들지 않고 활성 표시만 옮긴다."""
    _stage_or_404(stage)
    row = db.scalar(select(m.PromptTemplate).where(m.PromptTemplate.stage == stage, m.PromptTemplate.version == version))
    if row is None:
        raise HTTPException(404, f"{stage}의 버전 {version}이 없습니다.")
    db.execute(update(m.PromptTemplate).where(m.PromptTemplate.stage == stage).values(is_active=False))
    row.is_active = True
    db.commit()
    return _view(db, stage)
