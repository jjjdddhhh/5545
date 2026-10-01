# seed_prompts.py : 단계별 프롬프트 원문과 출력 JSON 스키마를 prompt_template에 버전 1로 넣는다.
# 출력 스키마를 손으로 적지 않고 Pydantic 모델(llm/schemas.py)에서 만들어, 모델 정의와 DB 기록이 어긋나지 않게 한다.
# 여러 번 실행해도 안전하다. 이미 버전 1이 있는 단계는 건너뛴다.
# 실행 방법(backend 폴더에서): python scripts/seed_prompts.py
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # scripts 폴더에서 실행해도 app 패키지를 찾게 한다

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.db import models as m  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.llm.prompt_store import file_prompt  # noqa: E402
from app.llm.schemas import STAGE_MODELS  # noqa: E402


def seed(db: Session) -> list[str]:
    """넣은 단계 이름 목록을 돌려준다. 테스트와 앱 시작 점검에서도 이 함수를 쓴다."""
    inserted = []
    for stage, model in STAGE_MODELS.items():
        exists = db.scalar(select(m.PromptTemplate.id)
                           .where(m.PromptTemplate.stage == stage, m.PromptTemplate.version == 1))
        if exists:
            continue
        # 다른 버전이 이미 활성이면(사용자가 고친 뒤) 버전 1을 활성으로 만들지 않는다.
        has_active = db.scalar(select(m.PromptTemplate.id)
                               .where(m.PromptTemplate.stage == stage, m.PromptTemplate.is_active.is_(True)))
        p = file_prompt(stage)
        db.add(m.PromptTemplate(stage=stage, version=1, system_prompt=p.system, user_template=p.user,
                                output_schema=model.model_json_schema(), is_active=not has_active))
        inserted.append(stage)
    db.commit()
    return inserted


def main() -> int:
    db = SessionLocal()
    try:
        inserted = seed(db)
    finally:
        db.close()
    if inserted:
        print("prompt_template에 버전 1을 넣었습니다: " + ", ".join(inserted))
    else:
        print("모든 단계에 버전 1이 이미 있습니다. 바꾼 것이 없습니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
