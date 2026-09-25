"""Structured tracing.

Every run writes one JSONL file: one object per event, in order, so a trace can
be tailed while a run is in flight and diffed between runs. The final event is
always ``run_end``, which carries the totals.

What is deliberately **not** traced: the redaction mapping, raw API keys, and
the un-redacted log. A trace is written to disk and attached to eval reports,
so it must be safe to share. Prompts and tool results *are* recorded, but they
only ever contain redacted text.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import ROOT

RUNS_DIR = ROOT / "runs"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


@dataclass
class Trace:
    """A single diagnosis run's trace.

    Use as a context manager so ``run_end`` is written even when the run raises.
    """

    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    path: Path | None = None
    events: list[dict] = field(default_factory=list)
    _t0: float = field(default_factory=time.perf_counter)
    _fh: Any = None

    # -- lifecycle ---------------------------------------------------------
    @classmethod
    def start(
        cls,
        meta: dict,
        *,
        out_dir: Path | None = None,
        enabled: bool = True,
        name: str | None = None,
    ) -> Trace:
        t = cls()
        if enabled:
            base = out_dir or (RUNS_DIR / datetime.now(UTC).strftime("%Y%m%dT%H%M%S"))
            base.mkdir(parents=True, exist_ok=True)
            t.path = base / f"{name or t.run_id}.jsonl"
            t._fh = t.path.open("w")
        t.event("run_start", **meta)
        return t

    def event(self, kind: str, **payload) -> dict:
        ev = {
            "ts": _now_iso(),
            "t_ms": round((time.perf_counter() - self._t0) * 1000, 1),
            "run_id": self.run_id,
            "kind": kind,
            **payload,
        }
        self.events.append(ev)
        if self._fh is not None:
            self._fh.write(json.dumps(ev, default=str) + "\n")
            self._fh.flush()
        return ev

    # -- convenience recorders --------------------------------------------
    def llm_call(
        self,
        *,
        step: int,
        model: str,
        provider: str,
        latency_ms: float,
        prompt_tokens: int | None,
        completion_tokens: int | None,
        total_tokens: int | None,
        finish: str | None,
        mode: str,
    ) -> None:
        self.event(
            "llm_call",
            step=step,
            model=model,
            provider=provider,
            latency_ms=round(latency_ms, 1),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            finish=finish,
            call_mode=mode,
        )

    def tool_call(
        self, *, step: int, name: str, args: dict, result: dict, latency_ms: float
    ) -> None:
        self.event(
            "tool_call",
            step=step,
            name=name,
            args=args,
            latency_ms=round(latency_ms, 1),
            result_bytes=len(json.dumps(result, default=str)),
            result_summary=_summarize(name, result),
        )

    def validation(self, *, attempt: int, ok: bool, errors: list[str]) -> None:
        self.event("validation", attempt=attempt, ok=ok, errors=errors)

    def finish(self, **payload) -> None:
        self.event("run_end", **payload)
        if self._fh is not None:
            self._fh.close()
            self._fh = None

    # -- totals ------------------------------------------------------------
    @property
    def totals(self) -> dict:
        calls = [e for e in self.events if e["kind"] == "llm_call"]
        tools = [e for e in self.events if e["kind"] == "tool_call"]
        return {
            "api_requests": len(calls),
            "tool_calls": len(tools),
            "prompt_tokens": sum(c.get("prompt_tokens") or 0 for c in calls),
            "completion_tokens": sum(c.get("completion_tokens") or 0 for c in calls),
            "total_tokens": sum(c.get("total_tokens") or 0 for c in calls),
            "llm_latency_ms": round(sum(c.get("latency_ms") or 0 for c in calls), 1),
            "wall_ms": round((time.perf_counter() - self._t0) * 1000, 1),
        }

    def __enter__(self) -> Trace:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._fh is not None:
            self.finish(ok=exc is None, error=None if exc is None else repr(exc))


def _summarize(name: str, result: dict) -> dict:
    """A few fields per tool, so a trace stays readable without the full payload."""
    if "error" in result:
        return {"error": result["error"]}
    if name == "search_log":
        return {
            "returned": result.get("returned"),
            "truncated": result.get("truncated"),
            "line_nos": [m["line_no"] for m in result.get("matches", [])],
        }
    if name == "get_timeline":
        return {
            "states": len(result.get("states", [])),
            "furthest_state": result.get("furthest_state"),
            "control_events": len(result.get("control_events", [])),
            "min_signal_dbm": result.get("min_signal_dbm"),
        }
    if name == "lookup_code":
        return {
            "kind": result.get("kind"),
            "code": result.get("code"),
            "found": result.get("found"),
        }
    if name == "retrieve_kb":
        return {
            "backend": result.get("backend"),
            "doc_ids": [r["doc_id"] for r in result.get("results", [])],
        }
    return {}
