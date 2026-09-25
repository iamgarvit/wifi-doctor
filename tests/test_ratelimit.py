"""The free-tier guard rails, driven by a fake clock so the tests stay instant."""

from __future__ import annotations

import pytest

from wifi_doctor.ratelimit import DailyQuotaExceeded, RateLimiter


class FakeClock:
    def __init__(self) -> None:
        self.t = 0.0
        self.slept: list[float] = []

    def now(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.t += seconds


@pytest.fixture
def limiter(tmp_path):
    clock = FakeClock()
    rl = RateLimiter("test", rpm=3, rpd=5, state_dir=tmp_path, sleep=clock.sleep, clock=clock.now)
    return rl, clock


def test_requests_under_the_rpm_do_not_sleep(limiter):
    rl, clock = limiter
    for _ in range(3):
        rl.acquire()
    assert clock.slept == []


def test_the_fourth_request_in_a_minute_waits_for_the_window(limiter):
    rl, clock = limiter
    for _ in range(4):
        rl.acquire()
    assert clock.slept and clock.slept[0] == pytest.approx(60.05, abs=0.1)


def test_daily_counter_persists_across_instances(tmp_path):
    a = RateLimiter("test", rpm=60, rpd=10, state_dir=tmp_path)
    a.acquire()
    a.acquire()
    b = RateLimiter("test", rpm=60, rpd=10, state_dir=tmp_path)
    assert b.used_today() == 2 and b.remaining_today() == 8


def test_daily_quota_raises_once_spent(limiter):
    rl, _ = limiter
    for _ in range(5):
        rl.acquire()
    with pytest.raises(DailyQuotaExceeded, match="5/5"):
        rl.acquire()


def test_estimate_reports_whether_a_plan_fits(limiter):
    rl, _ = limiter
    ok, msg = rl.estimate_fits(4)
    assert ok and "4 requests" in msg
    over, msg2 = rl.estimate_fits(99)
    assert not over and "OVER BUDGET" in msg2


def test_providers_have_separate_budgets(tmp_path):
    a = RateLimiter("gemini", rpm=60, rpd=5, state_dir=tmp_path)
    b = RateLimiter("groq", rpm=60, rpd=5, state_dir=tmp_path)
    a.acquire()
    assert a.used_today() == 1 and b.used_today() == 0


def test_a_corrupt_counter_file_is_treated_as_zero(tmp_path):
    rl = RateLimiter("test", rpm=60, rpd=5, state_dir=tmp_path)
    rl.acquire()
    next(tmp_path.glob("test_*.json")).write_text("{ corrupt")
    assert rl.used_today() == 0
