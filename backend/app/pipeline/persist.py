# persist.py : 여러 곳에서 똑같이 해야 하는 DB 쓰기를 모은다.
# 생성 실행(runner), 직접 수정 API(PATCH), 장면 재생성, 수정 제안 승인이 모두 이 함수들을 써서
# "내레이션을 바꾸면 자막을 코드로 다시 나눈다", "사용자가 고친 필드는 edited_fields와 revision에 남긴다" 같은
# 규칙(설계서 10절 규칙 1, 3)이 경로마다 달라지지 않게 한다. 커밋은 부르는 쪽이 한다.
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.db import models as m
from app.pipeline import budget as budget_mod
from app.pipeline import subtitles


def save_narration(db: Session, scene: m.Scene, text: str, setting: m.GenerationSetting,
                   is_edited: bool = False) -> m.Narration:
    """장면의 내레이션을 만들거나 바꾸고 자막 큐를 다시 만든다.
    글자 수와 예상 낭독 시간은 코드가 다시 계산한다(설계서 10절 규칙 3: 자막은 LLM 없이 즉시 다시 나눈다)."""
    narr = scene.narration
    if narr is None:
        narr = m.Narration(scene=scene, body="", char_count=0, est_duration_sec=Decimal("0"), is_edited=False)
        db.add(narr)
    narr.body = text
    narr.char_count = budget_mod.count_chars(text)
    narr.est_duration_sec = Decimal(str(budget_mod.estimate_duration_sec(text, setting.narration_cpm)))
    if is_edited:
        narr.is_edited = True     # 한 번 사람이 고친 내레이션은 이후 재생성에서 보호한다(다시 false로 돌리지 않는다)
    resplit_cues(db, narr, scene.duration_sec, setting.subtitle_max_chars)
    return narr


def resplit_cues(db: Session, narr: m.Narration, duration_sec: int, max_chars: int) -> list[m.SubtitleCue]:
    """내레이션의 자막 큐를 모두 지우고 다시 만든다(검수 C06·C07이 실패했을 때의 자동 수정도 이 함수다).
    cues 관계에 delete-orphan을 걸어 두어, 목록을 바꾸면 빠진 큐가 DB에서도 지워진다."""
    narr.cues = [m.SubtitleCue(seq=c["seq"], start_ms=c["start_ms"], end_ms=c["end_ms"], body=c["body"])
                 for c in subtitles.build_cues(narr.body, duration_sec, max_chars)]
    db.flush()
    return narr.cues


def mark_edited(obj: Any, field_name: str) -> None:
    """scene과 manual_step의 edited_fields에 필드 이름을 더한다(설계서 10절 규칙 1).
    JSON 컬럼은 리스트를 제자리에서 고치면 SQLAlchemy가 변경을 알아채지 못하므로 새 리스트를 대입한다."""
    current = list(obj.edited_fields or [])
    if field_name not in current:
        obj.edited_fields = current + [field_name]


def add_revision(db: Session, entity_type: str, entity_id: int, field_name: str,
                 before: Optional[Any], after: Optional[Any], user_id: int) -> m.Revision:
    """수정 이력 한 줄. 값은 문자열로 남긴다(MEDIUMTEXT). None은 NULL로 남겨 "값이 없었다"를 구분한다."""
    rev = m.Revision(entity_type=entity_type, entity_id=entity_id, field_name=field_name,
                     before_value=None if before is None else str(before),
                     after_value=None if after is None else str(after), user_id=user_id)
    db.add(rev)
    return rev


def setting_of_scene(db: Session, scene: m.Scene) -> m.GenerationSetting:
    """장면이 만들어진 실행의 생성 조건. 자막 글자 수와 낭독 속도는 그 실행의 조건을 따른다."""
    run = db.get(m.GenerationRun, scene.outline.run_id)
    return db.get(m.GenerationSetting, run.setting_id)
