# budget 테스트: 설계서 4절 2단계의 장면 수와 글자 수 예산 규칙(DB 없이 돈다).
import pytest

from app import config
from app.pipeline import budget as b


def test_duration_only_uses_30_seconds_per_scene():
    r = b.compute_budget(target_duration_sec=150)
    assert r.scene_count == 5
    assert r.durations == [30] * 5
    assert r.char_budgets == [150] * 5               # 30초 * 분당 300자 = 150자


def test_rounding_of_scene_count_and_even_split():
    assert b.compute_budget(target_duration_sec=160).scene_count == 5    # 5.33은 5
    r = b.compute_budget(target_duration_sec=170)
    assert r.scene_count == 6                                             # 5.67은 6
    assert sum(r.durations) == 170 and max(r.durations) - min(r.durations) <= 1


def test_scene_count_only_and_both():
    r = b.compute_budget(scene_count=4)
    assert r.total_sec == 120 and r.durations == [30] * 4
    r = b.compute_budget(target_duration_sec=100, scene_count=3)
    assert r.durations == [34, 33, 33]                                    # 나머지는 앞 장면부터
    assert r.char_budgets == [170, 165, 165]


def test_custom_speed_and_limits():
    r = b.compute_budget(target_duration_sec=60, scene_default_sec=20, narration_cpm=240)
    assert r.scene_count == 3 and r.char_budgets == [80, 80, 80]
    assert b.compute_budget(target_duration_sec=5).scene_count == 1      # 최소 1장면
    assert b.compute_budget(scene_count=500).scene_count == config.MAX_SCENES
    assert b.compute_budget(target_duration_sec=3, scene_count=5).durations == [1] * 5  # 장면당 최소 1초
    with pytest.raises(ValueError):
        b.compute_budget()


def test_char_count_and_tolerance():
    assert b.count_chars("드릴을 켜기 전에\n확인합니다.") == 13           # 공백과 줄바꿈은 세지 않는다
    assert b.estimate_duration_sec("가" * 150) == 30.0
    assert b.within_tolerance(128, 150) and b.within_tolerance(172, 150)  # 150 * 0.85 = 127.5, 150 * 1.15 = 172.5
    assert not b.within_tolerance(127, 150) and not b.within_tolerance(173, 150)
