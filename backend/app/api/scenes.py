# scenes.py : 장면과 내레이션 수정·재생성·순서 API(설계서 6절, 10절 수정·재생성 규칙 1~3).
# 모든 수정은 같은 순서를 따른다: 값 바꾸기, revision 남기기, edited_fields 기록, 커밋, 코드 검수 다시 하기.
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import config
from app.api import deps
from app.api.schemas import (NarrationPatch, OutlineView, RegenerateIn, RegenerateOut, SceneCreate, SceneOrderIn,
                             SceneOut, ScenePatch)
from app.api.views import outline_view, scene_check_status, scene_out
from app.db import models as m
from app.db.session import get_db
from app.llm import llm_client
from app.llm.prompt_store import active_prompt
from app.pipeline import budget as budget_mod
from app.pipeline import persist, review
from app.pipeline.narration import generate_narration
from app.pipeline.runner import DbRecorder, apply_detail, narration_input, scene_input
from app.pipeline.scene_detail import DETAIL_FIELDS, generate_scene_detail

router = APIRouter(tags=["장면"])

SCENE_FIELDS = ("title", "key_point", "screen_description", "visual_suggestion", "on_screen_text")


def _scene_response(db: Session, scene: m.Scene) -> SceneOut:
    """수정 뒤 화면에 돌려줄 장면. 다시 검수한 결과로 점 색(check_status)과 시작 시각을 채운다."""
    db.refresh(scene)
    outline = scene.outline
    start = sum(s.duration_sec for s in outline.scenes if s.seq < scene.seq)
    status = scene_check_status(db, outline.run_id, list(outline.scenes))
    return scene_out(scene, start, status.get(scene.id, "none"))


@router.patch("/api/scenes/{scene_id}", response_model=SceneOut)
def patch_scene(scene_id: int, body: ScenePatch, db: Session = Depends(get_db)):
    """장면의 제목, 학습 포인트, 화면 설명, 시각자료 제안, 화면 텍스트를 고친다.
    바뀐 필드마다 revision을 남기고 edited_fields에 이름을 더해, 이후 재생성에서 덮어쓰지 않게 한다(규칙 1, 2)."""
    scene = deps.get_or_404(db, m.Scene, scene_id, "장면")
    changes = body.model_dump(exclude_unset=True)
    changed = False
    for f in SCENE_FIELDS:
        if f not in changes or changes[f] is None:
            continue
        new = changes[f].strip()
        old = getattr(scene, f)
        if new == (old or ""):
            continue
        persist.add_revision(db, "scene", scene.id, f, old, new, config.DEFAULT_USER_ID)
        persist.mark_edited(scene, f)
        setattr(scene, f, new)
        changed = True
    if changed:
        db.commit()
        review.recheck_for_run_id(db, scene.outline.run_id)
    return _scene_response(db, scene)


@router.post("/api/scenes/{scene_id}/regenerate", response_model=RegenerateOut)
def regenerate_scene(scene_id: int, body: RegenerateIn = RegenerateIn(), db: Session = Depends(get_db)):
    """한 장면만 다시 생성한다(설계서 4절 "장면마다 따로 호출하므로 한 장면만 다시 만들 수 있다").
    - edited_fields에 있는 상세 필드는 프롬프트에 고정값으로 넘기고 결과에서도 덮어쓰지 않는다(규칙 2).
    - 사용자가 고친 내레이션(is_edited)은 다시 만들지 않는다.
    - LLM 호출은 그 장면이 만들어진 실행의 agent_step_log에 남는다. 요청이 끝날 때까지 기다리는 동기 API다
      (장면 하나는 보통 수십 초 안에 끝나므로 202와 SSE까지 쓰지 않았다)."""
    scene = deps.get_or_404(db, m.Scene, scene_id, "장면")
    outline = scene.outline
    run = db.get(m.GenerationRun, outline.run_id)
    setting = db.get(m.GenerationSetting, run.setting_id)
    source = db.get(m.SourceDocument, run.source_id)
    by_id = {p["id"]: p for p in source.paragraphs}
    recorder = DbRecorder(db, run.id)
    regenerated, kept = [], [f for f in (scene.edited_fields or []) if f in DETAIL_FIELDS]

    try:
        if "detail" in body.parts:
            res = generate_scene_detail(recorder, active_prompt(db, "scene_detail"), setting, outline.title,
                                        scene_input(scene), by_id, scene_ref=scene.id)
            apply_detail(scene, res.detail)
            regenerated.append("detail")
            db.commit()
        if "narration" in body.parts:
            if scene.narration is not None and scene.narration.is_edited:
                kept.append("narration")
            elif setting.content_type == "manual" and scene.narration is None:
                pass   # 매뉴얼형만 만든 프로젝트에는 내레이션이 없으므로 새로 만들지 않는다
            else:
                res = generate_narration(recorder, active_prompt(db, "narration"), setting, narration_input(scene),
                                         by_id, ref=scene.id)
                persist.save_narration(db, scene, res.text, setting)
                regenerated.append("narration")
                db.commit()
    except llm_client.GenerationError as exc:
        db.rollback()
        raise HTTPException(502, f"모델이 형식에 맞는 답을 주지 않아 다시 생성하지 못했습니다: {exc}")
    except Exception as exc:  # Ollama가 꺼져 있거나 연결이 끊긴 경우
        db.rollback()
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(502, f"Ollama에 연결하지 못했습니다. Ollama가 켜져 있는지 확인해 주세요. ({exc})")

    review.recheck_for_run_id(db, run.id)
    return RegenerateOut(scene=_scene_response(db, scene), regenerated=regenerated, kept=kept)


@router.put("/api/projects/{project_id}/scene-order", response_model=OutlineView)
def reorder_scenes(project_id: int, body: SceneOrderIn, db: Session = Depends(get_db)):
    """장면 순서를 바꾼다. 현재 구성안의 장면 id를 빠짐없이 한 번씩 보내야 한다.
    seq가 바뀐 장면마다 revision을 남긴다. 자막 시간은 장면 기준이라 바꿀 필요가 없고, SRT는 내보낼 때 새 순서로 누적된다."""
    deps.project_or_404(db, project_id)
    outline = deps.current_outline(db, project_id)
    if outline is None:
        raise HTTPException(404, "아직 생성된 구성안이 없습니다.")
    scenes = {s.id: s for s in outline.scenes}
    if sorted(body.scene_ids) != sorted(scenes) or len(set(body.scene_ids)) != len(body.scene_ids):
        raise HTTPException(400, "현재 구성안의 장면 id를 빠짐없이 한 번씩 보내 주세요.")
    for seq, sid in enumerate(body.scene_ids, 1):
        sc = scenes[sid]
        if sc.seq != seq:
            persist.add_revision(db, "scene", sc.id, "seq", sc.seq, seq, config.DEFAULT_USER_ID)
            sc.seq = seq
    db.commit()
    db.expire(outline, ["scenes"])     # relationship의 정렬(seq 순서)을 다시 읽게 한다
    return outline_view(db, outline)


@router.post("/api/projects/{project_id}/scenes", response_model=SceneOut, status_code=201)
def add_scene(project_id: int, body: SceneCreate, db: Session = Depends(get_db)):
    """현재 구성안의 맨 뒤에 사용자가 만든 장면을 더한다(와이어프레임의 "+ 장면 추가").
    시간과 글자 수 예산은 코드가 정한다(장면당 기본 시간, 분당 글자 수). 화면 설명 등은 "이 장면만 다시 생성"으로 채울 수 있다.
    사용자가 쓴 제목과 학습 포인트는 edited_fields에 넣어 재생성에서 보호한다."""
    deps.project_or_404(db, project_id)
    outline = deps.current_outline(db, project_id)
    if outline is None:
        raise HTTPException(404, "아직 생성된 구성안이 없습니다. 먼저 생성해 주세요.")
    run = db.get(m.GenerationRun, outline.run_id)
    setting = db.get(m.GenerationSetting, run.setting_id)
    source = db.get(m.SourceDocument, run.source_id)
    valid = {p["id"] for p in source.paragraphs}
    unknown = [p for p in body.source_paragraphs if p not in valid]
    if unknown:
        raise HTTPException(400, f"원고에 없는 문단 번호입니다: {', '.join(unknown)}")
    duration = setting.scene_default_sec
    scene = m.Scene(seq=len(outline.scenes) + 1, title=body.title.strip(),
                    key_point=(body.key_point.strip() or body.title.strip())[:500],
                    source_paragraphs=list(dict.fromkeys(body.source_paragraphs)), duration_sec=duration,
                    char_budget=budget_mod.char_budget(duration, setting.narration_cpm),
                    edited_fields=["title", "key_point"])
    outline.scenes.append(scene)   # 관계 목록에 직접 넣어, 같은 세션에서 읽어 둔 목록에도 새 장면이 보이게 한다
    db.flush()
    persist.add_revision(db, "scene", scene.id, "created", None, scene.title, config.DEFAULT_USER_ID)
    db.commit()
    review.recheck_for_run_id(db, run.id)
    return _scene_response(db, scene)


@router.patch("/api/narrations/{narration_id}", response_model=SceneOut)
def patch_narration(narration_id: int, body: NarrationPatch, db: Session = Depends(get_db)):
    """내레이션을 고치고, 자막을 LLM 없이 코드로 즉시 다시 나눈다(설계서 10절 규칙 3).
    고친 내레이션은 is_edited가 true가 되어 이후 장면 재생성에서 덮어쓰지 않는다. 변경 전후는 revision에 남는다."""
    narr = deps.get_or_404(db, m.Narration, narration_id, "내레이션")
    scene = narr.scene
    new_text = body.body.strip()
    if new_text != narr.body:   # 같은 내용을 다시 저장하면 이력을 남기지 않는다
        persist.add_revision(db, "narration", narr.id, "body", narr.body, new_text, config.DEFAULT_USER_ID)
        persist.save_narration(db, scene, new_text, persist.setting_of_scene(db, scene), is_edited=True)
        db.commit()
        review.recheck_for_run_id(db, scene.outline.run_id)
    return _scene_response(db, scene)
