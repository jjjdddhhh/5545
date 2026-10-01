# llm_step.py : 생성 단계가 LLM을 부르는 공통 통로.
# 실제 호출은 언제나 llm_client.generate 하나로 한다(CLAUDE.md 결정 5). 이 파일은 그 앞뒤에서
#   1) 템플릿에 값을 채우고,
#   2) 전역 잠금으로 LLM 요청을 한 번에 하나만 보내고(GPU 하나, 설계서 12절 "동시 요청 수 1"),
#   3) llm_client가 돌려준 시도별 로그(토큰 수, 걸린 시간, 잘림 위험)를 기록기에 넘긴다.
# 기록기는 runner에서는 agent_step_log에 쓰고, 스크립트(smoke_ollama)에서는 메모리 목록에 쓴다.
import threading
from typing import Any, Optional, Protocol, TypeVar

from pydantic import BaseModel

from app.llm import llm_client
from app.llm.prompt_store import PromptSet, render

T = TypeVar("T", bound=BaseModel)

# 프로세스 전체에서 하나뿐인 잠금. 생성 실행, 장면 재생성, 수정 요청 에이전트가 모두 이 잠금을 잡고 LLM을 부른다.
# GPU 하나에서 동시 요청은 어차피 줄을 서서 처리되고 메모리만 더 쓰므로(설계서 12절), 앱이 직접 순서를 정한다.
# RLock이 아니라 Lock인 이유: 한 스레드가 잠금을 잡은 채 다시 LLM을 부르는 경로가 없어야 하고,
# 그런 코드가 생기면 멈춤(교착)으로 바로 드러나게 하기 위해서다.
LLM_LOCK = threading.Lock()

# 단계별 temperature(설계서 12절): 구조와 사실은 매번 같게(0.2), 읽히는 문장은 조금 더 자연스럽게(0.6).
TEMPERATURE = {"outline": 0.2, "scene_detail": 0.2, "narration": 0.6, "manual": 0.6, "chunk_summary": 0.2}

# agent_step_log.input_json에 프롬프트 전문을 남기되, 너무 긴 원고가 로그를 키우지 않도록 자른다.
# 2만 자는 8192 토큰 컨텍스트에 들어가는 원고보다 넉넉히 크므로 실제로는 거의 잘리지 않는다.
LOG_TEXT_LIMIT = 20000


class StepRecorder(Protocol):
    """LLM 시도 하나(attempt)마다 한 번 불린다. log는 llm_client가 만든 딕셔너리다
    (attempt, model, tokens_in, tokens_out, latency_ms, truncation_risk, status).
    truncation_hits는 지금까지 기록한 시도 가운데 잘림 위험(truncation_risk)이 표시된 수다.
    구성안 단계가 이 값으로 "원고가 잘렸을 수 있으니 요약본으로 다시 만든다"를 판단한다(설계서 12절)."""
    truncation_hits: int

    def record(self, stage: str, template_id: Optional[int], log: dict,
               input_json: Any, output_json: Any) -> None: ...


class ListRecorder:
    """메모리에만 쌓는 기록기. 스크립트와 테스트에서 쓴다."""
    def __init__(self) -> None:
        self.rows: list[dict] = []
        self.truncation_hits = 0

    def record(self, stage, template_id, log, input_json, output_json) -> None:
        if log.get("truncation_risk"):
            self.truncation_hits += 1
        self.rows.append({"stage": stage, "template_id": template_id, **log,
                          "input_json": input_json, "output_json": output_json})


def call_llm(recorder: StepRecorder, stage: str, prompt: PromptSet, values: dict, out_model: type[T],
             feedback: Optional[str] = None, target: Optional[dict] = None) -> T:
    """템플릿을 채워 LLM을 한 번(형식 오류면 llm_client 안에서 1회 더) 부르고, 검증된 출력 모델을 돌려준다.

    feedback: 코드 검수(C02, C03, C04, C08, C11)에 걸려 단계를 다시 요청할 때, 무엇이 틀렸는지 적은 문장.
              사용자 프롬프트 끝에 붙여 같은 실수를 고치게 한다.
    target:   이 호출이 어느 장면·단계에 대한 것인지(로그 검색용). 예: {"scene_seq": 3}
    실패하면 llm_client.GenerationError를 그대로 올린다. 그 전에 실패한 시도의 로그도 모두 기록한다."""
    system = render(prompt.system, values)
    user = render(prompt.user, values)
    if feedback:
        user += "\n\n[앞의 답을 검수한 결과 고칠 점]\n" + feedback + "\n위 문제를 고쳐 같은 형식으로 다시 답한다."
    input_json = {"system": system[:LOG_TEXT_LIMIT], "user": user[:LOG_TEXT_LIMIT],
                  "template_version": prompt.version, "target": target or {}, "feedback": feedback}
    temperature = TEMPERATURE.get(stage, 0.2)

    with LLM_LOCK:   # 잠금 안에서는 LLM 호출만 한다. DB 기록은 잠금을 푼 뒤에 해서 다른 요청을 오래 막지 않는다.
        try:
            parsed, logs = llm_client.generate(system, user, out_model, temperature=temperature)
            error = None
        except llm_client.GenerationError as exc:
            parsed, logs, error = None, exc.logs, exc

    for log in logs:
        # 마지막 시도만 결과를 가진다. 앞 시도(형식 오류로 재요청한 것)는 결과 없이 상태만 남긴다.
        is_last = log is logs[-1]
        output = parsed.model_dump() if (parsed is not None and is_last) else None
        recorder.record(stage, prompt.template_id, log, input_json,
                        {"output": output, "truncation_risk": log.get("truncation_risk", False),
                         "model": log.get("model")})
    if error is not None:
        raise error
    return parsed
