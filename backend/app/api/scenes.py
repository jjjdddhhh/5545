# scenes.py : 장면과 내레이션 수정 API(설계서 6절, 10절 수정·재생성 규칙).
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import config
from app.api import deps
from app.api.schemas import NarrationPatch, SceneOut
from app.api.views import scene_out
from app.db import models as m
from app.db.session import get_db
from app.pipeline import persist

router = APIRouter(tags=["장면"])


@router.patch("/api/narrations/{narration_id}", response_model=SceneOut)
def patch_narration(narration_id: int, body: NarrationPatch, db: Session = Depends(get_db)):
    """내레이션을 고치고, 자막을 LLM 없이 코드로 즉시 다시 나눈다(설계서 10절 규칙 3).
    고친 내레이션은 is_edited가 true가 되어 이후 장면 재생성에서 덮어쓰지 않는다. 변경 전후는 revision에 남는다."""
    narr = deps.get_or_404(db, m.Narration, narration_id, "내레이션")
    new_text = body.body.strip()
    if new_text != narr.body:   # 같은 내용을 다시 저장하면 이력을 남기지 않는다
        persist.add_revision(db, "narration", narr.id, "body", narr.body, new_text, config.DEFAULT_USER_ID)
        scene = narr.scene
        persist.save_narration(db, scene, new_text, persist.setting_of_scene(db, scene), is_edited=True)
        db.commit()
    return scene_out(narr.scene)
