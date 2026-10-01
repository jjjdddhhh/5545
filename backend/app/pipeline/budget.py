# budget.py : 2단계 분량 계산(설계서 4절). LLM을 부르지 않고 코드로만 계산한다.
# 원칙: "LLM은 문장을 쓰고, 숫자와 규칙은 코드가 계산한다." 장면 수, 장면별 시간, 내레이션 글자 수 예산을
# 여기서 정해 LLM에게 틀로 넘긴다. 같은 입력이면 언제나 같은 결과가 나와야 한다(재현성).
from dataclasses import dataclass, field

from app import config


@dataclass
class Budget:
    scene_count: int                                          # 장면 수
    total_sec: int                                            # 전체 분량(초)
    durations: list[int] = field(default_factory=list)       # 장면별 시간(초), 길이는 scene_count
    char_budgets: list[int] = field(default_factory=list)    # 장면별 내레이션 글자 수 예산(공백 제외)
    narration_cpm: int = config.NARRATION_CPM                 # 계산에 쓴 분당 글자 수(나중에 다시 계산할 때 쓴다)

    def as_dict(self) -> dict:
        """agent_step_log.output_json과 API 응답에 그대로 넣을 수 있는 모양."""
        return {"scene_count": self.scene_count, "total_sec": self.total_sec, "durations": self.durations,
                "char_budgets": self.char_budgets, "narration_cpm": self.narration_cpm}


def char_budget(duration_sec: int, narration_cpm: int = config.NARRATION_CPM) -> int:
    """장면 시간 동안 읽을 수 있는 글자 수. 분당 글자 수를 초 단위로 바꿔 곱한다.
    예: 30초 * 300자/60초 = 150자. 소수점은 반올림하고, 최소 1자로 둔다(0자 예산은 검수할 수 없다)."""
    return max(1, round(duration_sec * narration_cpm / 60))


def split_evenly(total: int, n: int) -> list[int]:
    """total을 n개의 정수로 최대한 고르게 나눈다. 나머지는 앞 장면부터 1씩 더한다.
    예: 100초를 3장면으로 나누면 [34, 33, 33]. 합은 언제나 total과 같다(자막 타이밍 합계 검수 C07의 전제)."""
    base, rest = divmod(total, n)
    return [base + (1 if i < rest else 0) for i in range(n)]


def compute_budget(target_duration_sec: int | None = None,
                   scene_count: int | None = None,
                   scene_default_sec: int = config.SCENE_DEFAULT_SEC,
                   narration_cpm: int = config.NARRATION_CPM) -> Budget:
    """설계서 4절 2단계 규칙.

    1. 장면 수를 따로 받지 않으면, 목표 분량을 장면당 기본 시간(30초)으로 나눠 장면 수를 정한다.
       나눈 값은 반올림한다. 150초면 5장면, 160초면 5장면(5.3), 170초면 6장면(5.7)이다.
       반올림 대신 올림을 쓰면 장면 하나가 지나치게 짧아질 수 있어(예: 160초를 6장면이면 장면당 26초) 반올림을 골랐다.
    2. 장면 수만 받으면, 전체 분량은 장면 수 * 장면당 기본 시간이다.
    3. 둘 다 받으면, 목표 분량을 그 장면 수로 고르게 나눈다.
    4. 장면별 글자 수 예산은 장면 시간 * 분당 글자 수 / 60이다.
    """
    if target_duration_sec is None and scene_count is None:
        # API(SettingIn)에서 이미 막지만, 다른 경로(스크립트)에서 불렀을 때를 위해 한 번 더 확인한다.
        raise ValueError("목표 분량과 장면 수 중 하나는 있어야 합니다.")
    if scene_default_sec <= 0 or narration_cpm <= 0:
        raise ValueError("장면당 기본 시간과 분당 글자 수는 0보다 커야 합니다.")

    if scene_count is None:
        # 규칙 1. 최소 1장면, 최대 config.MAX_SCENES 장면으로 자른다.
        n = round(target_duration_sec / scene_default_sec)
        n = min(max(1, n), config.MAX_SCENES)
        total = target_duration_sec
    else:
        n = min(max(1, scene_count), config.MAX_SCENES)
        # 규칙 2와 3.
        total = target_duration_sec if target_duration_sec is not None else n * scene_default_sec

    # 장면당 1초는 있어야 자막 시간을 배분할 수 있다. 장면 수가 분량(초)보다 많으면 분량을 장면 수로 올린다.
    total = max(total, n)
    durations = split_evenly(total, n)
    return Budget(scene_count=n, total_sec=total, durations=durations,
                  char_budgets=[char_budget(d, narration_cpm) for d in durations],
                  narration_cpm=narration_cpm)


def count_chars(text: str) -> int:
    """내레이션 글자 수. 공백(띄어쓰기, 줄바꿈)은 소리 내어 읽지 않으므로 빼고 센다(config.NARRATION_CPM 주석 참고).
    narration.char_count와 검수 C04가 모두 이 함수로 센다."""
    return sum(1 for ch in text if not ch.isspace())


def estimate_duration_sec(text: str, narration_cpm: int = config.NARRATION_CPM) -> float:
    """내레이션을 읽는 데 걸릴 예상 시간(초). narration.est_duration_sec DECIMAL(5,1)에 맞춰 소수 첫째 자리로 반올림한다."""
    return round(count_chars(text) * 60 / narration_cpm, 1)


def within_tolerance(chars: int, budget: int, tolerance: float = config.NARRATION_TOLERANCE) -> bool:
    """글자 수가 예산의 ±허용 오차 안에 있는지(검수 C04). 경계값은 통과로 본다."""
    return budget * (1 - tolerance) <= chars <= budget * (1 + tolerance)
