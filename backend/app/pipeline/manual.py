# manual.py : 5b단계 맞춤 매뉴얼·주의사항(설계서 4절). 매뉴얼형 콘텐츠를 만든다.
# LLM은 대상과 난이도에 맞춘 단계별 지시, 주의사항, 단계별 소요 기간을 원고에서 뽑아 쓴다.
# 수치는 원고에 있는 값만 쓴다. 생성 직후 C08(수치 대조), C03(근거 문단), C11(출력 언어)을 확인해
# 실패하면 매뉴얼 단계를 1회 다시 요청한다(설계서 10절 C08 "매뉴얼 단계를 1회 다시 요청한다").
# 날짜 배치는 schedule.py가 한다.
from dataclasses import dataclass, field

from app.llm.prompt_store import PromptSet, common_values
from app.llm.schemas import ManualOut
from app.pipeline import checks
from app.pipeline.llm_step import StepRecorder, call_llm
from app.pipeline.schedule import clamp_days
from app.pipeline.text_cleaner import to_prompt


@dataclass
class ManualResult:
    manual: ManualOut
    retried: bool = False
    failures: list[checks.CheckResult] = field(default_factory=list)


def outline_text(title: str, summary: str, objectives: list[str], scenes: list[tuple[int, str, str]]) -> str:
    """구성안을 매뉴얼 프롬프트에 넣을 글로 바꾼다. scenes는 (순서, 제목, 학습 포인트) 목록이다.
    구성안도 모델이 만든 결과이므로 <source> 태그로 감싸 자료로만 읽히게 한다(프롬프트 인젝션 대비)."""
    lines = [f"제목: {title}", f"요약: {summary}", "학습목표: " + "; ".join(objectives)]
    lines += [f"{seq}. {t} - {kp}" for seq, t, kp in scenes]
    return "<source>\n" + "\n".join(lines) + "\n</source>"


def evidence_text(paragraphs_by_id: dict[str, dict], ids: list[str], fallback: str) -> str:
    """단계의 근거 문단 원문. 근거 번호가 하나도 맞지 않으면 원고 전체(fallback)와 대조한다.
    그 경우 근거 문단이 없다는 사실은 C03이 따로 알려 준다."""
    texts = [paragraphs_by_id[i]["text"] for i in ids if i in paragraphs_by_id]
    return "\n".join(texts) if texts else fallback


def validate(out: ManualOut, paragraphs_by_id: dict[str, dict], language: str) -> list[checks.CheckResult]:
    """매뉴얼 직후의 검수. 실패한 결과만 돌려준다. 대상 식별값은 단계 seq다(저장 뒤 runner가 DB id로 바꾼다)."""
    full = "\n".join(p["text"] for p in paragraphs_by_id.values())
    results: list[checks.CheckResult] = []
    for st in out.steps:
        ev = evidence_text(paragraphs_by_id, st.source_paragraphs, full)
        text = " ".join(x for x in (st.title, st.instruction, st.tip or "") if x)
        r = checks.check_numbers(text, ev, "manual_step", st.seq, label=f"단계 {st.seq}: ")
        r.data["seq"] = st.seq
        results.append(r)
    for i, c in enumerate(out.cautions, 1):
        # 주의사항에는 근거 문단 번호가 없으므로 원고 전체와 대조한다.
        results.append(checks.check_numbers(c.body, full, "manual", None, label=f"주의사항 {i}: "))
    results += checks.check_sources([{"seq": st.seq, "source_paragraphs": st.source_paragraphs} for st in out.steps],
                                    set(paragraphs_by_id), "manual_step")
    all_text = " ".join([out.title, out.intro, *(s.instruction for s in out.steps), *(c.body for c in out.cautions)])
    results.append(checks.check_language(all_text, language, "manual"))
    return [r for r in results if r.failed]


def normalize(out: ManualOut, paragraph_ids: set[str]) -> ManualOut:
    """저장 전에 코드로 고칠 수 있는 것을 고친다. 단계 순서를 1부터 다시 매기고, 없는 문단 번호를 지우고,
    기간과 주기를 1~365일로 맞춘다(일정 배치 C09의 전제)."""
    for i, st in enumerate(out.steps, 1):
        st.seq = i
        st.source_paragraphs = [p for p in dict.fromkeys(st.source_paragraphs) if p in paragraph_ids]
        st.duration_days = clamp_days(st.duration_days, 1)
        st.interval_days = clamp_days(st.interval_days, None)
    return out


def generate_manual(recorder: StepRecorder, prompt: PromptSet, setting, outline_summary: str,
                    paragraphs: list[dict]) -> ManualResult:
    """매뉴얼을 만든다. 실패(GenerationError)는 위로 올리고, runner가 C01 실패로 기록한다."""
    by_id = {p["id"]: p for p in paragraphs}
    values = {**common_values(setting), "outline": outline_summary, "source_text": to_prompt(paragraphs)}
    out = call_llm(recorder, "manual", prompt, values, ManualOut, target={"audience": setting.audience})
    failures = validate(out, by_id, setting.output_language)
    retried = False
    if failures:
        retried = True
        out = call_llm(recorder, "manual", prompt, values, ManualOut, feedback=checks.feedback_text(failures),
                       target={"audience": setting.audience, "retry": True})
        failures = validate(out, by_id, setting.output_language)
    return ManualResult(manual=normalize(out, set(by_id)), retried=retried, failures=failures)
