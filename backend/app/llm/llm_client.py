# llm_client.py : 모든 LLM 단계가 이 함수 하나로 Ollama를 부른다.
import os
import time
from typing import Optional, TypeVar

from ollama import Client
from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)

# 백엔드와 Ollama가 같은 노트북에서 Docker 없이 돈다고 가정한다. 값은 .env로 바꿀 수 있다.
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
MODEL = os.getenv("OLLAMA_MODEL", "qwen3:8b")  # 설계서 12절 기본 모델. 비교 실험 때 exaone3.5:7.8b로 바꾼다
THINK: Optional[bool] = False  # qwen3의 생각 과정 출력을 끈다. 생각 모드가 없는 모델로 바꾸면 None으로 둔다.
NUM_CTX = int(os.getenv("OLLAMA_NUM_CTX", "8192"))  # 8GB VRAM에서 8B 모델(4비트) 가중치와 KV 캐시가 함께 들어가는 크기
KEEP_ALIVE = "30m"             # 한 번 실행하는 동안 모델을 메모리에 올려 두어 다시 읽는 시간을 없앤다
TRUNCATION_RATIO = 0.95        # 입력 토큰이 한도의 95%를 넘으면 원고 앞부분이 잘렸을 가능성이 크다고 본다

client = Client(host=OLLAMA_HOST)


class GenerationError(Exception):
    """재요청까지 실패했을 때 올린다. 단계 로그를 함께 넘겨 agent_step_log에 남긴다."""

    def __init__(self, message: str, logs: list[dict]):
        super().__init__(message)
        self.logs = logs


def generate(system: str, user: str, out_model: type[T],
             temperature: float = 0.2) -> tuple[T, list[dict]]:
    """스키마를 강제한 JSON을 받아 Pydantic으로 검증한다.
    검증에 실패하면 오류 내용을 붙여 1회만 다시 요청한다(10절 C01)."""
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    logs: list[dict] = []

    for attempt in (1, 2):  # 재시도는 1회로 제한해 실행 시간을 예측할 수 있게 한다
        started = time.perf_counter()
        resp = client.chat(
            model=MODEL,
            messages=messages,
            format=out_model.model_json_schema(),  # 모델이 이 스키마대로만 출력하도록 제한한다
            think=THINK,
            options={"num_ctx": NUM_CTX, "temperature": temperature},
            keep_alive=KEEP_ALIVE,
        )
        tokens_in = resp.prompt_eval_count or 0
        log = {
            "attempt": attempt,
            "model": MODEL,
            "tokens_in": tokens_in,
            "tokens_out": resp.eval_count or 0,
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "truncation_risk": tokens_in >= NUM_CTX * TRUNCATION_RATIO,
        }
        content = resp.message.content or ""
        try:
            parsed = out_model.model_validate_json(content)
            log["status"] = "ok"
            logs.append(log)
            return parsed, logs
        except ValidationError as err:
            log["status"] = "retry" if attempt == 1 else "failed"
            logs.append(log)
            messages.append({"role": "assistant", "content": content})
            messages.append({
                "role": "user",
                "content": "앞의 답에 형식 오류가 있다. 아래 오류를 고쳐 같은 스키마로 다시 답하라.\n" + str(err),
            })

    raise GenerationError(f"{out_model.__name__} 생성 실패", logs)
