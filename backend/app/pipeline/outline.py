# outline.py : 3단계 구조화·구성안(설계서 4절, 9절).
# LLM이 원고를 읽고 제목, 요약, 학습목표, 장면 목록(장면마다 근거 문단 번호)을 만든다.
# 장면 수는 2단계(budget)가 정한 값을 그대로 넘긴다. 코드는 원고 구조를 추측해 장면을 나누지 않는다(결정 3).
#
# 생성 직후 코드 검수 C02(장면 수), C03(근거 문단), C11(출력 언어)을 돌려, 실패하면 이 단계만 1회 다시 요청한다
# (설계서 10절 "실패했을 때" 칸). 그래도 실패하면 결과를 그대로 쓰고 실패 내용을 돌려줘 6단계가 경고로 저장한다.
from dataclasses import dataclass, field
from typing import Optional

from app.llm import llm_client
from app.llm.prompt_store import PromptSet, common_values, file_prompt
from app.llm.schemas import ChunkSummaryOut, OutlineOut
from app.pipeline import checks
from app.pipeline.llm_step import StepRecorder, call_llm
from app.pipeline.text_cleaner import to_prompt

# ---------- 긴 원고 대비(설계서 12절) ----------
# 원고 토큰 수는 글자 수로 어림한다. 한국어는 qwen 계열 토크나이저에서 대략 글자 1~1.5개가 토큰 1개지만,
# 넘쳐서 잘리는 것보다 미리 나누는 편이 안전하므로 "글자 1개 = 토큰 1개"로 보수적으로 센다.
CHARS_PER_TOKEN = 1.0
# 컨텍스트에서 원고를 뺀 나머지 몫. 시스템·사용자 지시문 약 800토큰, 구성안 출력 약 2,000토큰(장면 40개 기준)을 남긴다.
RESERVED_TOKENS = 2800


def source_token_budget(num_ctx: Optional[int] = None) -> int:
    """원고에 쓸 수 있는 토큰 수. 8192 컨텍스트면 5,392토큰이다."""
    return max(1000, (num_ctx or llm_client.NUM_CTX) - RESERVED_TOKENS)


def estimate_tokens(text: str) -> int:
    return int(len(text) / CHARS_PER_TOKEN)


def chunk_paragraphs(paragraphs: list[dict], max_chars: int) -> list[list[dict]]:
    """문단을 번호 순서대로 max_chars 이하의 묶음으로 나눈다. 원고에 절 구분이 있다고 가정하지 않기 위해
    내용이 아니라 길이로만 나눈다(설계서 12절). 문단 하나가 max_chars보다 길어도 쪼개지 않고 혼자 한 묶음이 된다."""
    chunks: list[list[dict]] = []
    cur: list[dict] = []
    size = 0
    for p in paragraphs:
        n = len(p["text"])
        if cur and size + n > max_chars:
            chunks.append(cur)
            cur, size = [], 0
        cur.append(p)
        size += n
    if cur:
        chunks.append(cur)
    return chunks


def summarize_long_source(recorder: StepRecorder, paragraphs: list[dict], max_chars: int) -> str:
    """원고가 컨텍스트에 다 들어가지 않을 때, 묶음마다 요점을 뽑아 문단 번호와 함께 모은다.
    결과는 to_prompt와 같은 <source> 모양이며, 각 줄 앞에 그 요점의 근거 문단 번호를 붙여 근거 추적을 잃지 않는다."""
    prompt = file_prompt("chunk_summary")   # prompt_template의 stage 값에 없어 파일 원문만 쓴다
    lines = []
    for i, chunk in enumerate(chunk_paragraphs(paragraphs, max_chars), 1):
        out = call_llm(recorder, "chunk_summary", prompt, {"clean_paragraphs": to_prompt(chunk)},
                       ChunkSummaryOut, target={"chunk": i})
        valid = {p["id"] for p in chunk}
        for pt in out.points:
            ids = [x for x in pt.source_paragraphs if x in valid] or [chunk[0]["id"]]  # 엉뚱한 번호는 버린다
            lines.append(f"[{', '.join(ids)}] {pt.summary}")
    return "<source>\n" + "\n".join(lines) + "\n</source>"


@dataclass
class OutlineResult:
    outline: OutlineOut
    retried: bool = False                                # 코드 검수 때문에 1회 다시 요청했는지
    failures: list[checks.CheckResult] = field(default_factory=list)   # 다시 요청한 뒤에도 남은 실패
    summarized: bool = False                             # 긴 원고라 요약본으로 구성했는지


def validate(out: OutlineOut, scene_count: int, paragraph_ids: set[str], language: str) -> list[checks.CheckResult]:
    """구성안 직후에 돌리는 검수. 실패한 결과만 돌려준다."""
    items = [{"seq": s.seq, "source_paragraphs": s.source_paragraphs} for s in out.scenes]
    text = " ".join([out.title, out.summary, *out.learning_objectives, *(s.title + " " + s.key_point for s in out.scenes)])
    results = [checks.check_scene_count(len(out.scenes), scene_count),
               *checks.check_sources(items, paragraph_ids, "scene"),
               checks.check_language(text, language, "outline")]
    return [r for r in results if r.failed]


def generate_outline(recorder: StepRecorder, prompt: PromptSet, setting, paragraphs: list[dict],
                     scene_count: int) -> OutlineResult:
    """구성안을 만든다. setting은 GenerationSetting 행(또는 같은 속성을 가진 객체)이다.
    실패(GenerationError)는 위로 올린다. 구성안이 없으면 이후 단계를 할 수 없어 실행 전체가 실패한다."""
    source_text = to_prompt(paragraphs)
    budget_tokens = source_token_budget()
    summarized = False
    if estimate_tokens(source_text) > budget_tokens:
        # 미리 어림한 크기가 이미 넘치면 처음부터 요약본으로 구성한다.
        source_text = summarize_long_source(recorder, paragraphs, int(budget_tokens * CHARS_PER_TOKEN * 0.8))
        summarized = True

    values = {**common_values(setting), "scene_count": scene_count, "clean_paragraphs": source_text}
    trunc_before = _truncation_count(recorder)
    out = call_llm(recorder, "outline", prompt, values, OutlineOut, target={"scene_count": scene_count})

    # 어림은 통과했지만 Ollama가 실제로 잘림 위험을 알렸다면(입력 토큰이 한도의 95% 이상), 요약본으로 한 번 더 만든다.
    if not summarized and _truncation_count(recorder) > trunc_before:
        source_text = summarize_long_source(recorder, paragraphs, int(budget_tokens * CHARS_PER_TOKEN * 0.6))
        summarized = True
        values["clean_paragraphs"] = source_text
        out = call_llm(recorder, "outline", prompt, values, OutlineOut, target={"scene_count": scene_count})

    ids = {p["id"] for p in paragraphs}
    failures = validate(out, scene_count, ids, setting.output_language)
    retried = False
    if failures:
        # 설계서 10절: C02, C03, C11이 실패하면 해당 단계를 1회 다시 요청한다.
        retried = True
        out = call_llm(recorder, "outline", prompt, values, OutlineOut,
                       feedback=checks.feedback_text(failures), target={"scene_count": scene_count, "retry": True})
        failures = validate(out, scene_count, ids, setting.output_language)
    return OutlineResult(outline=normalize(out, ids), retried=retried, failures=failures, summarized=summarized)


def normalize(out: OutlineOut, paragraph_ids: set[str]) -> OutlineOut:
    """저장하기 전에 코드로 고칠 수 있는 것만 고친다.
    - seq는 모델이 건너뛰거나 겹치게 쓸 수 있어 배열 순서대로 1부터 다시 매긴다.
    - 원고에 없는 문단 번호는 지운다. 남는 번호가 없으면 빈 목록이 되어 6단계 C03에서 경고로 남는다.
      (없는 번호를 그대로 두면 화면에서 근거 문단을 열 때 오류가 나므로 지우는 편이 낫다.)"""
    for i, s in enumerate(out.scenes, 1):
        s.seq = i
        s.source_paragraphs = [p for p in dict.fromkeys(s.source_paragraphs) if p in paragraph_ids]
    return out


def _truncation_count(recorder: StepRecorder) -> int:
    """기록기에 지금까지 쌓인 잘림 위험 표시 수. 호출 전후 값을 비교해 이번 호출에서 잘림 위험이 났는지 안다."""
    return recorder.truncation_hits
