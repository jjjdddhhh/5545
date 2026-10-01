# repo.py : 수정 요청 에이전트(edit_agent.py)의 Repo 프로토콜을 SQLAlchemy로 구현한다(설계서 13절).
# 에이전트는 이 객체를 통해서만 DB를 읽는다. 쓰기 메서드는 하나도 없다(결정 8: 에이전트에는 쓰기 도구가 없다).
#
# 가드레일
# - 프로젝트 범위: 에이전트는 자기 프로젝트의 "현재" 구성안·매뉴얼만 볼 수 있다. 다른 프로젝트나 예전 실행의
#   장면 id를 넣으면 KeyError를 올리고, edit_agent가 그 호출을 error로 기록한다.
# - 도구 결과가 대화에 쌓여 컨텍스트(NUM_CTX)를 차지하므로, 조회 결과는 필요한 필드만 짧게 돌려준다.
# - 자막 미리보기(split_subtitles)는 단계 3의 subtitles.split_subtitles, 제안 검수(check)는 단계 5의 검수 함수를 쓴다.
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import config
from app.api import deps
from app.db import models as m
from app.pipeline import checks, subtitles

# 조회 결과에 넣는 검수 메시지 수의 상한. 장면 하나에 걸린 검수는 보통 5~6개라 10개면 충분하고,
# 그 이상은 컨텍스트만 차지한다.
MAX_CHECK_ITEMS = 10


class SqlRepo:
    def __init__(self, db: Session, project_id: int):
        self.db = db
        self.project_id = project_id
        # 요청 하나를 처리하는 동안 현재 결과가 바뀌지 않는다고 보고 처음에 한 번만 찾는다.
        self.outline = deps.current_outline(db, project_id)
        self.manual = deps.current_manual(db, project_id)
        run_id = self.outline.run_id if self.outline else (self.manual.run_id if self.manual else None)
        self.run = db.get(m.GenerationRun, run_id) if run_id else None
        self.setting = db.get(m.GenerationSetting, self.run.setting_id) if self.run else None
        source = db.get(m.SourceDocument, self.run.source_id) if self.run else None
        self.paragraphs_by_id: dict[str, dict] = {p["id"]: p for p in (source.paragraphs if source else [])}

    # ---------- 내부 도우미 ----------
    def _scene(self, scene_id: int) -> m.Scene:
        """현재 구성안에 속한 장면만 돌려준다. 아니면 KeyError(에이전트에게는 오류 메시지로 돌아간다)."""
        scene = self.db.get(m.Scene, scene_id)
        if scene is None or self.outline is None or scene.outline_id != self.outline.id:
            raise KeyError(f"이 프로젝트의 현재 구성안에 장면 id {scene_id}가 없습니다. get_project_overview의 scene_id를 쓰세요.")
        return scene

    def _step(self, step_id: int) -> m.ManualStep:
        step = self.db.get(m.ManualStep, step_id)
        if step is None or self.manual is None or step.manual_id != self.manual.id:
            raise KeyError(f"이 프로젝트의 현재 매뉴얼에 단계 id {step_id}가 없습니다. get_project_overview의 step_id를 쓰세요.")
        return step

    def _checks_for(self, target_pairs: set[tuple[str, int]]) -> list[dict]:
        """대상(종류, id) 목록에 걸린 자동 검수 결과 가운데 통과하지 못한 것을 짧게 돌려준다."""
        if self.run is None:
            return []
        rows = self.db.scalars(select(m.ReviewCheck).where(m.ReviewCheck.run_id == self.run.id,
                                                           m.ReviewCheck.check_code.like("C%"))).all()
        out = [{"code": r.check_code, "result": r.result, "message": r.message}
               for r in rows if (r.target_type, r.target_id) in target_pairs and r.result != "pass"]
        return out[:MAX_CHECK_ITEMS]

    def evidence(self, ids: list[str]) -> str:
        """근거 문단 원문을 이은 글. 근거가 없으면 원고 전체를 쓴다(수치 대조 C08을 할 수 있게)."""
        texts = [self.paragraphs_by_id[i]["text"] for i in ids if i in self.paragraphs_by_id]
        return "\n".join(texts) if texts else "\n".join(p["text"] for p in self.paragraphs_by_id.values())

    # ---------- Repo 프로토콜 ----------
    def overview(self, project_id: int) -> dict:
        """장면 목록, 매뉴얼 단계 목록, 검수 요약. 장면은 순서(seq)와 id를 함께 주어 "3번 장면"을 id로 바꿀 수 있게 한다."""
        scenes = [{"scene_id": s.id, "seq": s.seq, "title": s.title, "key_point": s.key_point,
                   "user_edited_fields": list(s.edited_fields or [])}
                  for s in (self.outline.scenes if self.outline else [])]
        steps = [{"step_id": st.id, "seq": st.seq, "title": st.title}
                 for st in (self.manual.steps if self.manual else [])]
        summary = {}
        if self.run is not None:
            from app.pipeline.review import summarize   # 순환 import를 피하려고 함수 안에서 불러온다
            summary = summarize(self.db, self.run.id)
        return {"scenes": scenes, "manual_steps": steps, "check_summary": summary,
                "keywords": list(self.setting.keywords or []) if self.setting else []}

    def scene(self, scene_id: int) -> dict:
        s = self._scene(scene_id)
        narr = s.narration
        targets = {("scene", s.id)} | ({("narration", narr.id), ("subtitle", narr.id)} if narr else set())
        return {"id": s.id, "seq": s.seq, "title": s.title, "key_point": s.key_point,
                "screen_description": s.screen_description or "", "visual_suggestion": s.visual_suggestion or "",
                "on_screen_text": s.on_screen_text or "", "duration_sec": s.duration_sec,
                "char_budget": s.char_budget, "source_paragraphs": list(s.source_paragraphs or []),
                "narration": narr.body if narr else "",
                "narration_chars": narr.char_count if narr else 0,
                "subtitles": [c.body for c in narr.cues] if narr else [],
                "user_edited_fields": list(s.edited_fields or []) + (["narration"] if narr and narr.is_edited else []),
                "checks": self._checks_for(targets)}

    def paragraphs(self, project_id: int, ids: list[str]) -> list[dict]:
        """요청한 문단 번호의 원문. 없는 번호는 건너뛴다. 원문은 edit_agent가 <source> 태그로 감싼다."""
        return [{"id": i, "text": self.paragraphs_by_id[i]["text"]} for i in ids if i in self.paragraphs_by_id]

    def manual_step(self, step_id: int) -> dict:
        st = self._step(step_id)
        return {"id": st.id, "seq": st.seq, "title": st.title, "instruction": st.instruction, "tip": st.tip or "",
                "source_paragraphs": list(st.source_paragraphs or []),
                "user_edited_fields": list(st.edited_fields or []),
                "checks": self._checks_for({("manual_step", st.id)})}

    def edited_fields(self, target_type: str, target_id: int) -> list[str]:
        """사용자가 직접 고친 필드 목록(제안에 경고 표시를 붙이는 데 쓴다).
        edit_agent는 내레이션 제안의 target_id로 장면 id를 넘기므로, narration이면 장면의 내레이션을 본다."""
        if target_type == "scene":
            return list(self._scene(target_id).edited_fields or [])
        if target_type == "narration":
            narr = self._scene(target_id).narration
            return ["body"] if narr is not None and narr.is_edited else []
        if target_type == "manual_step":
            return list(self._step(target_id).edited_fields or [])
        return []

    def split_subtitles(self, text: str) -> list[str]:
        max_chars = self.setting.subtitle_max_chars if self.setting else config.SUBTITLE_MAX_CHARS
        return subtitles.split_subtitles(text, max_chars)

    def check(self, proposals: list[dict]) -> list[dict]:
        """지금까지 만든 제안에 검수 규칙(설계서 10절)을 적용한다. 제안마다 결과 목록과 통과 여부를 돌려준다."""
        return [{"proposal_no": i, "target_type": p["target_type"], "field": p["field_name"],
                 **check_proposal(self, p)} for i, p in enumerate(proposals, 1)]


def check_proposal(repo: SqlRepo, p: dict) -> dict:
    """제안 하나를 검수한다. 적용하는 항목:
    - 모든 제안: C11(출력 언어), C12(과장·단정 표현), C08(수치가 근거 문단에 있는지. 에이전트가 원고에 없는 수치를 넣는 것을 막는다)
    - 내레이션 제안: C04(글자 수 예산), C06(자막 미리보기 줄 길이)
    - 장면·단계 필드: 비어 있지 않은지, 화면 텍스트는 300자 이하인지(DB 컬럼 길이)
    결과는 {"ok": 통과 여부, "results": [{"code","result","message"}]}이다."""
    language = repo.setting.output_language if repo.setting else "ko"
    source_all = "\n".join(x["text"] for x in repo.paragraphs_by_id.values())
    hype = checks.load_terms("hype_terms.txt")
    text = p.get("after_value") or ""
    results: list[checks.CheckResult] = []

    if not text.strip():
        results.append(checks.CheckResult("C01", checks.FAIL, "바꿀 값이 비어 있습니다."))
    if p["target_type"] == "narration":
        scene = repo._scene(int(p["target_id"]))
        results.append(checks.check_budget(text, scene.char_budget, "narration", scene.id))
        cues = [{"seq": i, "body": b} for i, b in enumerate(repo.split_subtitles(text), 1)]
        results.append(checks.check_subtitle_lines(cues, repo.setting.subtitle_max_chars if repo.setting
                                                   else config.SUBTITLE_MAX_CHARS))
        evidence = repo.evidence(list(scene.source_paragraphs or []))
    elif p["target_type"] == "scene":
        scene = repo._scene(int(p["target_id"]))
        if p["field_name"] == "on_screen_text" and len(text) > 300:
            results.append(checks.CheckResult("C01", checks.FAIL, "화면 텍스트는 300자를 넘을 수 없습니다."))
        evidence = repo.evidence(list(scene.source_paragraphs or []))
    else:
        step = repo._step(int(p["target_id"]))
        evidence = repo.evidence(list(step.source_paragraphs or []))

    results.append(checks.check_numbers(text, evidence, p["target_type"]))
    results.append(checks.check_language(text, language, p["target_type"]))
    results.append(checks.check_hype(text, hype, source_all, p["target_type"]))
    bad = [r for r in results if r.result in (checks.FAIL, checks.WARN)]
    return {"ok": not any(r.result == checks.FAIL for r in results),
            "results": [{"code": r.code, "result": r.result, "message": r.message} for r in bad] or
                       [{"code": "ALL", "result": "pass", "message": "검수를 모두 통과했습니다."}]}


def scene_map_note(repo: SqlRepo) -> Optional[str]:
    """사용자 요청 뒤에 붙일 참고 정보. 작은 모델이 "3번 장면"의 3을 장면 id로 착각하지 않도록
    순서와 id의 대응을 미리 알려 준다. 이 글도 기존 결과이므로 <source> 태그로 감싼다(결정 8)."""
    lines = []
    if repo.outline is not None:
        lines += [f"장면 {s.seq}번 = scene_id {s.id} ({s.title})" for s in repo.outline.scenes]
    if repo.manual is not None:
        lines += [f"매뉴얼 {st.seq}단계 = step_id {st.id} ({st.title})" for st in repo.manual.steps]
    if not lines:
        return None
    return ("[참고] 장면 번호(seq)와 도구에 넣는 id는 다르다. 도구에는 반드시 id를 넣는다.\n<source>\n"
            + "\n".join(lines) + "\n</source>")
