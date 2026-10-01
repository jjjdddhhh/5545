# settings.py : 생성 조건 저장·조회 API(설계서 6절).
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api import deps
from app.api.schemas import SettingIn, SettingOut
from app.db import models as m
from app.db.session import get_db

router = APIRouter(prefix="/api/projects/{project_id}/settings", tags=["생성 조건"])


@router.put("", response_model=SettingOut)
def save_settings(project_id: int, body: SettingIn, db: Session = Depends(get_db)):
    """필수 설정과 고급 설정을 저장한다.
    기존 행을 고치지 않고 매번 새 행을 만든다. generation_run.setting_id가 실행 당시의 설정을 가리키므로,
    덮어쓰면 "이전 실행은 어떤 조건으로 돌렸는가"를 잃기 때문이다(실행끼리 비교, 설계서 7절)."""
    deps.project_or_404(db, project_id)
    setting = m.GenerationSetting(project_id=project_id, **body.model_dump())
    db.add(setting)
    db.commit()
    return setting


@router.get("", response_model=SettingOut)
def get_settings(project_id: int, db: Session = Depends(get_db)):
    """가장 최근 설정. 조건 설정 화면을 다시 열 때 이전 값을 채워 넣는 데 쓴다."""
    deps.project_or_404(db, project_id)
    setting = deps.latest_setting(db, project_id)
    if setting is None:
        raise HTTPException(404, "아직 생성 조건을 저장하지 않았습니다.")
    return setting
