"""Settings, loaded once from the environment (and ``.env`` if present).

Nothing here ever prints a key. ``Settings.redacted()`` is what goes into
traces and reports.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]

DEFAULT_MODELS = {
    # Verified against models.list() for this key on 2026-09-25:
    # gemini-2.5-flash-lite now returns 404 "no longer available to new users"
    # and Google's own error points at gemini-3.5-flash-lite.
    "gemini": "gemini-3.5-flash-lite",
    "groq": "llama-3.3-70b-versatile",
    "mock": "mock-1",
}


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    provider: str
    model: str
    gemini_api_key: str | None
    groq_api_key: str | None
    rpm: int
    rpd: int
    demo_max_runs_per_session: int
    demo_daily_cap: int

    @property
    def api_key(self) -> str | None:
        return {"gemini": self.gemini_api_key, "groq": self.groq_api_key}.get(self.provider)

    @property
    def has_key(self) -> bool:
        return self.provider == "mock" or bool(self.api_key)

    def redacted(self) -> dict:
        """Safe to write to a trace or a report."""
        return {
            "provider": self.provider,
            "model": self.model,
            "rpm": self.rpm,
            "rpd": self.rpd,
            "api_key_present": bool(self.api_key),
        }


@lru_cache(maxsize=1)
def _load_env() -> None:
    load_dotenv(ROOT / ".env", override=False)


def get_settings(provider: str | None = None, model: str | None = None) -> Settings:
    _load_env()
    prov = (provider or os.environ.get("LLM_PROVIDER") or "gemini").strip().lower()
    mdl = model or os.environ.get("LLM_MODEL") or DEFAULT_MODELS.get(prov, "")
    # An LLM_MODEL set for Gemini must not leak into a --provider groq run.
    if provider and os.environ.get("LLM_MODEL") and not model:
        env_prov = (os.environ.get("LLM_PROVIDER") or "gemini").strip().lower()
        if env_prov != prov:
            mdl = DEFAULT_MODELS.get(prov, mdl)
    return Settings(
        provider=prov,
        model=mdl,
        gemini_api_key=os.environ.get("GEMINI_API_KEY") or None,
        groq_api_key=os.environ.get("GROQ_API_KEY") or None,
        rpm=_int("LLM_RPM", 15),
        rpd=_int("LLM_RPD", 500),
        demo_max_runs_per_session=_int("DEMO_MAX_RUNS_PER_SESSION", 5),
        demo_daily_cap=_int("DEMO_DAILY_CAP", 100),
    )
