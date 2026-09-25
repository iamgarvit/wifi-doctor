"""Client-side guard rails for free-tier APIs.

Two limits, because the free tiers have two:

* **requests per minute** — enforced in-process with a sliding window; the
  caller simply blocks until a slot frees up.
* **requests per day** — enforced with a small JSON counter on disk, keyed by
  provider and UTC date, so it survives across processes. An eval run that is
  interrupted and resumed must not get a fresh daily budget.

The daily counter is advisory: it exists to stop this project from burning a
day's quota by accident, not as a security boundary.
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections import deque
from datetime import UTC, datetime
from pathlib import Path

from .config import ROOT


class DailyQuotaExceeded(RuntimeError):
    """Raised when the configured requests-per-day budget is spent."""


class RateLimiter:
    def __init__(
        self,
        provider: str,
        rpm: int,
        rpd: int,
        *,
        state_dir: Path | None = None,
        sleep=time.sleep,
        clock=time.monotonic,
    ) -> None:
        self.provider = provider
        self.rpm = max(1, rpm)
        self.rpd = max(1, rpd)
        self._window: deque[float] = deque()
        self._lock = threading.Lock()
        self._sleep = sleep
        self._clock = clock
        self._dir = state_dir or (ROOT / ".cache" / "ratelimit")

    # -- daily counter -----------------------------------------------------
    def _path(self) -> Path:
        day = datetime.now(UTC).strftime("%Y-%m-%d")
        return self._dir / f"{self.provider}_{day}.json"

    def used_today(self) -> int:
        p = self._path()
        if not p.exists():
            return 0
        try:
            return int(json.loads(p.read_text()).get("count", 0))
        except (json.JSONDecodeError, ValueError, OSError):
            return 0

    def remaining_today(self) -> int:
        return max(0, self.rpd - self.used_today())

    def _bump(self) -> None:
        p = self._path()
        p.parent.mkdir(parents=True, exist_ok=True)
        count = self.used_today() + 1
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps({"provider": self.provider, "count": count}))
        os.replace(tmp, p)

    # -- acquire -----------------------------------------------------------
    def acquire(self) -> None:
        """Block until one request may be made. Raises if the daily budget is spent."""
        with self._lock:
            if self.used_today() >= self.rpd:
                raise DailyQuotaExceeded(
                    f"{self.provider}: {self.used_today()}/{self.rpd} requests used today "
                    f"(LLM_RPD). Resume tomorrow, raise LLM_RPD, or use --limit."
                )
            while True:
                now = self._clock()
                while self._window and now - self._window[0] >= 60.0:
                    self._window.popleft()
                if len(self._window) < self.rpm:
                    self._window.append(now)
                    break
                wait = 60.0 - (now - self._window[0]) + 0.05
                self._sleep(max(0.0, wait))
            self._bump()

    def estimate_fits(self, n_requests: int) -> tuple[bool, str]:
        """Check a planned number of requests against the remaining daily budget."""
        left = self.remaining_today()
        ok = n_requests <= left
        msg = (
            f"{self.provider}: plan {n_requests} requests, {left} of {self.rpd} left today "
            f"({self.used_today()} used). Estimated wall time at {self.rpm} rpm: "
            f"~{n_requests / self.rpm:.1f} min."
        )
        if not ok:
            msg += f"  OVER BUDGET by {n_requests - left}."
        return ok, msg
