# deps.py : 여러 라우터가 함께 쓰는 조회 도우미.
# 라우터마다 "없으면 404" 코드를 반복하지 않도록 여기 모았다.
# 모든 함수는 호출한 쪽의 세션(db)을 그대로 쓰며, 커밋은 하지 않는다(읽기 전용).
from typing import TypeVar

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models as m

T = TypeVar("T")  # get_or_404가 넘겨받은 모델 형식을 그대로 돌려주도록 형식 변수를 쓴다


def get_or_404(db: Session, model: type[T], obj_id: int, label: str) -> T:
    """기본키로 한 행을 읽는다. 없으면 화면에 그대로 보여 줄 수 있는 한국어 메시지로 404를 올린다.
    label은 메시지에 들어갈 이름이다(예: "장면", "매뉴얼 단계")."""
    obj = db.get(model, obj_id)  # 세션 안에 이미 읽은 객체가 있으면 DB를 다시 부르지 않는다
    if obj is None:
        raise HTTPException(status_code=404, detail=f"{label}을(를) 찾을 수 없습니다 (id {obj_id}).")
    return obj


def project_or_404(db: Session, project_id: int) -> m.Project:
    """프로젝트 경로(/api/projects/{id}/...)를 쓰는 모든 엔드포인트가 처음에 부른다."""
    return get_or_404(db, m.Project, project_id, "프로젝트")


# ---------- "가장 최근 것" 조회 ----------
# 원고와 설정은 고칠 때마다 새 행을 만들어 이력을 남긴다(이전 실행이 어떤 원고·설정으로 돌았는지 보존).
# 그래서 "현재 값"은 id가 가장 큰 행이다. created_at 대신 id로 정렬하는 이유는,
# 같은 초에 두 행이 생기면 created_at으로는 순서를 가릴 수 없기 때문이다.

def latest_source(db: Session, project_id: int) -> m.SourceDocument | None:
    """프로젝트의 가장 최근 원고. 아직 원고를 넣지 않았으면 None."""
    return db.scalars(select(m.SourceDocument).where(m.SourceDocument.project_id == project_id)
                      .order_by(m.SourceDocument.id.desc()).limit(1)).first()


def latest_setting(db: Session, project_id: int) -> m.GenerationSetting | None:
    """프로젝트의 가장 최근 생성 조건. 아직 설정하지 않았으면 None."""
    return db.scalars(select(m.GenerationSetting).where(m.GenerationSetting.project_id == project_id)
                      .order_by(m.GenerationSetting.id.desc()).limit(1)).first()


def latest_run(db: Session, project_id: int) -> m.GenerationRun | None:
    """가장 최근 생성 실행. 진행 중이거나 실패한 실행일 수도 있다(목록 화면의 최근 실행 상태 표시에 쓴다)."""
    return db.scalars(select(m.GenerationRun).where(m.GenerationRun.project_id == project_id)
                      .order_by(m.GenerationRun.id.desc()).limit(1)).first()


# ---------- "현재 결과" 조회 ----------
# 설계서 10절 규칙 4: 다시 생성하면 이전 결과는 is_current만 false가 된 채 보존된다.
# 따라서 화면에 보여 줄 결과는 is_current가 true인 행이다. 정상이라면 프로젝트당 하나뿐이지만,
# 혹시 둘 이상이 남아 있어도 가장 최근 것을 고르도록 id 내림차순으로 하나만 가져온다.

def current_outline(db: Session, project_id: int) -> m.Outline | None:
    """현재 구성안. 생성이 한 번도 끝나지 않았으면 None."""
    return db.scalars(select(m.Outline).where(m.Outline.project_id == project_id, m.Outline.is_current.is_(True))
                      .order_by(m.Outline.id.desc()).limit(1)).first()


def current_manual(db: Session, project_id: int) -> m.Manual | None:
    """현재 매뉴얼. 영상형만 생성했거나 생성 전이면 None."""
    return db.scalars(select(m.Manual).where(m.Manual.project_id == project_id, m.Manual.is_current.is_(True))
                      .order_by(m.Manual.id.desc()).limit(1)).first()
