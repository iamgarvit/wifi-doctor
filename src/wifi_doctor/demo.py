"""Framework-neutral core of the public demo.

The Gradio app (``app.py``, for Hugging Face Spaces) and the Streamlit app
(``streamlit_app.py``, for Streamlit Community Cloud) are thin front ends over
this module: input preparation, the example logs, the per-session and daily
run limits, the call into the agent with its friendly failure messages, and
the HTML/Markdown renderers all live here, once.

Public-demo discipline lives in :func:`check_quota`: a per-session run cap and
a process-wide daily cap, both configurable, plus a friendly message instead of
a stack trace when the API key is missing or the quota is spent.
"""

from __future__ import annotations

import html
import json
import logging
import os
import re
import threading
from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass
from datetime import UTC, datetime

from .agent import AgentResult, diagnose
from .baseline import classify
from .config import ROOT, Settings
from .llm import RateLimitError, build_provider
from .logparse import split_lines, truncate_for_prompt
from .ratelimit import DailyQuotaExceeded, RateLimiter
from .redact import redact_log
from .retrieval import get_kb
from .schema import Diagnosis, RootCause

_logger = logging.getLogger(__name__)

MAX_INPUT_LINES = 2000
EXAMPLES_PATH = ROOT / "data" / "synthetic" / "dev" / "cases.jsonl"

# UI label -> diagnose() mode. "baseline" never reaches an LLM.
MODES = {
    "agent (tools + RAG)": "agent",
    "single-shot (whole log, one prompt)": "single_shot",
    "rule baseline (no LLM)": "baseline",
}

# Process-wide daily cap. A restart resets this; it is a courtesy limit on a
# free key, not a billing control.
_daily = {"date": "", "count": 0}
_daily_lock = threading.Lock()


# --------------------------------------------------------------------------
# settings for a hosted demo
# --------------------------------------------------------------------------

# What a hosted demo may configure, and its defaults: the demo model has its
# own free quota, separate from the evaluation model's, and retrieval is
# BM25-only so the host never needs torch.
DEMO_SETTING_KEYS = (
    "GEMINI_API_KEY",
    "LLM_PROVIDER",
    "LLM_MODEL",
    "LLM_RPM",
    "LLM_RPD",
    "DEMO_MAX_RUNS_PER_SESSION",
    "DEMO_DAILY_CAP",
    "WIFI_DOCTOR_EMBEDDINGS",
)
DEMO_DEFAULTS = {
    "LLM_PROVIDER": "gemini",
    "LLM_MODEL": "gemini-3.1-flash-lite",
    "WIFI_DOCTOR_EMBEDDINGS": "0",
    "DEMO_MAX_RUNS_PER_SESSION": "5",
    # About 6 API requests per agent diagnosis, so ~300 of the model's free daily quota.
    "DEMO_DAILY_CAP": "50",
}


def apply_demo_settings(
    secrets: Mapping[str, object], environ: MutableMapping[str, str] = os.environ
) -> None:
    """Resolve each demo setting as secrets, then environment, then default.

    The winner is written into ``environ`` so that :func:`config.get_settings`
    and :mod:`retrieval` read it the usual way. Values are never logged.
    """
    for key in DEMO_SETTING_KEYS:
        value = secrets.get(key)
        if value is None or str(value).strip() == "":
            value = environ.get(key) or DEMO_DEFAULTS.get(key)
        if value is not None and str(value).strip() != "":
            environ[key] = str(value).strip()


# --------------------------------------------------------------------------
# inputs
# --------------------------------------------------------------------------


def load_examples() -> dict[str, str]:
    """One example log per root cause, taken from the dev split."""
    out: dict[str, str] = {}
    seen: set[str] = set()
    if not EXAMPLES_PATH.exists():
        return out
    for line in EXAMPLES_PATH.read_text().splitlines():
        case = json.loads(line)
        label = case["root_cause"]
        if label in seen:
            continue
        seen.add(label)
        out[f"{label}  ({case['n_lines']} lines, {case['variant']})"] = case["log"]
    return out


def prepare(log_text: str | None) -> tuple[str, str]:
    """Return (log, notice): the log trimmed for the demo, and why if it was."""
    log_text = (log_text or "").strip("\n")
    if not log_text.strip():
        return "", "Paste a log, upload a file, or pick an example."
    lines = split_lines(log_text)
    if len(lines) <= MAX_INPUT_LINES:
        return log_text, ""
    _, kept = truncate_for_prompt(lines, MAX_INPUT_LINES)
    notice = (
        f"Log is {len(lines):,} lines; trimmed to {len(kept):,} for the demo, keeping the "
        f"lines around every state change and control event. Line numbers below are "
        f"renumbered against the trimmed log."
    )
    return "\n".join(kept), notice


# --------------------------------------------------------------------------
# limits and messages
# --------------------------------------------------------------------------

NO_KEY_MESSAGE = (
    "### No API key configured\n\nThis demo needs a `GEMINI_API_KEY` secret. Get a free key "
    "at [aistudio.google.com/apikey](https://aistudio.google.com/apikey).\n\n"
    "Meanwhile, the **rule baseline** mode works with no key at all."
)

QUOTA_MESSAGE = (
    "### Free-tier quota spent\n\nThe model's free daily request quota is used up, or the "
    "provider is rate-limiting this demo. Try again later, or use the **rule baseline** "
    "mode, which needs no API access."
)


KEY_REJECTED_MESSAGE = (
    "### The demo's API key was rejected\n\nThe model provider did not accept the key configured "
    "for this demo (it may be invalid, revoked or restricted). The **rule baseline** mode still "
    "works, and you can run the full demo locally with your own free key; see the README."
)

PROVIDER_FAILED_MESSAGE = (
    "### The model could not be reached\n\nThe request to the model provider failed. Try again "
    "in a minute, or use the **rule baseline** mode, which needs no API access."
)

# Auth failures, as Gemini (and most providers) report them.
_KEY_REJECTED = re.compile(
    r"API_KEY_INVALID|API key not valid|PERMISSION_DENIED|UNAUTHENTICATED|\b40[13]\b",
    re.IGNORECASE,
)
# Anything shaped like a provider key, scrubbed from server-side logs as a backstop.
_KEY_LIKE = re.compile(
    r"AIza[0-9A-Za-z_\-]{10,}|\bAQ\.[0-9A-Za-z_\-]{10,}|\b(?:hf|gsk|sk)[_-][\w\-]{10,}"
)


def scrub(text: str, secret: str | None = None) -> str:
    """Remove the configured key, and anything key-shaped, from text bound for a log."""
    if secret:
        text = text.replace(secret, "[redacted]")
    return _KEY_LIKE.sub("[redacted]", text)


def failure_message(exc: BaseException, settings) -> str:
    """What a visitor sees when the model call fails: never the raw provider error.

    The details go to the server log only, with the key scrubbed out.
    """
    detail = scrub(f"{type(exc).__name__}: {exc}", getattr(settings, "api_key", None))
    _logger.warning("model call failed: %s", detail[:500])
    return KEY_REJECTED_MESSAGE if _KEY_REJECTED.search(str(exc)) else PROVIDER_FAILED_MESSAGE


def check_quota(session_runs: int, settings) -> str | None:
    """Return a user-facing refusal message, or None when the run may proceed."""
    if session_runs >= settings.demo_max_runs_per_session:
        return (
            f"### Session limit reached\n\nThis public demo allows "
            f"**{settings.demo_max_runs_per_session} runs per session** so one visitor cannot "
            f"spend the whole free-tier quota. Reload the page to start a new session, or run "
            f"it locally — see the README. The **rule baseline** mode still works and makes no "
            f"API calls."
        )
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    with _daily_lock:
        if _daily["date"] != today:
            _daily.update(date=today, count=0)
        spent = _daily["count"] >= settings.demo_daily_cap
    if spent:
        return (
            f"### Daily cap reached\n\nThis demo has used its **{settings.demo_daily_cap} "
            f"diagnoses for today** (UTC). Please come back tomorrow, or run it locally with "
            f"your own free Gemini API key. The **rule baseline** mode still works."
        )
    return None


# --------------------------------------------------------------------------
# one run
# --------------------------------------------------------------------------


@dataclass
class Outcome:
    """Everything a front end needs to render one click of *Diagnose*."""

    log: str
    notice: str
    mode: str
    diagnosis: Diagnosis | None = None  # unredacted, ready to show
    result: AgentResult | None = None  # None for the baseline
    message: str | None = None  # Markdown shown instead of a diagnosis
    used_run: bool = False  # counts against the session limit


def run(log_text: str | None, mode_label: str, session_runs: int, settings: Settings) -> Outcome:
    log, notice = prepare(log_text)
    mode = MODES.get(mode_label, "agent")
    if not log:
        return Outcome(log="", notice=notice, mode=mode, message=f"### {notice}")

    if mode == "baseline":
        return Outcome(log=log, notice=notice, mode=mode, diagnosis=classify(log))

    if not settings.has_key:
        return Outcome(log=log, notice=notice, mode=mode, message=NO_KEY_MESSAGE)

    if refusal := check_quota(session_runs, settings):
        return Outcome(log=log, notice=notice, mode=mode, message=refusal)

    limiter = RateLimiter(settings.provider, settings.rpm, settings.rpd)
    try:
        provider = build_provider(settings, rate_limiter=limiter)
        result = diagnose(log, provider, mode=mode, kb=get_kb(), trace_enabled=False)
    except (DailyQuotaExceeded, RateLimitError):
        # Either the local daily budget (LLM_RPD) or the provider's own quota,
        # which the provider layer gives up on without a long backoff.
        return Outcome(log=log, notice=notice, mode=mode, message=QUOTA_MESSAGE)
    except Exception as exc:  # noqa: BLE001 - a visitor never sees a raw error or traceback
        return Outcome(log=log, notice=notice, mode=mode, message=failure_message(exc, settings))

    with _daily_lock:
        _daily["count"] += 1
    return Outcome(
        log=log,
        notice=notice,
        mode=result.mode,
        diagnosis=result.display(),
        result=result,
        used_run=True,
    )


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------

_SEVERITY = {RootCause.HEALTHY: ("#0f7b30", "#e8f6ec", "No fault found")}


def card_html(diagnosis: Diagnosis, mode: str, notice: str) -> str:
    healthy = diagnosis.root_cause is RootCause.HEALTHY
    colour, bg, _ = _SEVERITY.get(diagnosis.root_cause, ("#a8331a", "#fdeeea", "Failure"))
    conf = f"{diagnosis.confidence:.0%}"
    bits = [
        f'<div style="border-left:6px solid {colour};background:{bg};padding:14px 16px;'
        f'border-radius:6px;margin-bottom:12px;color:#1f2328">',
        f'<div style="font-size:1.35em;font-weight:700;color:{colour}">'
        f"{html.escape(diagnosis.root_cause.value)}</div>",
        f'<div style="opacity:.75;font-size:.9em;margin-top:2px">confidence {conf} · '
        f"mode <code>{html.escape(mode)}</code>"
        + (" · <b>needs more info</b>" if diagnosis.needs_more_info else "")
        + "</div>",
        f'<p style="margin:10px 0 0">{html.escape(diagnosis.summary)}</p>',
        "</div>",
    ]
    if notice:
        bits.append(f'<p style="font-size:.85em;opacity:.7">{html.escape(notice)}</p>')
    if diagnosis.evidence:
        bits.append("<h4>Evidence</h4><ul>")
        for ev in diagnosis.evidence:
            bits.append(
                f"<li><code>line {ev.line_no}</code> — <code>{html.escape(ev.quote[:160])}</code>"
                f'<br><span style="opacity:.8">{html.escape(ev.why)}</span></li>'
            )
        bits.append("</ul>")
    elif not healthy:
        bits.append("<p><i>No evidence was cited.</i></p>")
    if diagnosis.suggested_fixes:
        bits.append("<h4>Suggested fixes</h4><ol>")
        bits += [f"<li>{html.escape(f)}</li>" for f in diagnosis.suggested_fixes]
        bits.append("</ol>")
    if diagnosis.kb_citations:
        cites = ", ".join(f"<code>{html.escape(c)}</code>" for c in diagnosis.kb_citations)
        bits.append(f"<h4>Knowledge base</h4><p>{cites}</p>")
    return "".join(bits)


def highlighted_log_html(log: str, evidence) -> str:
    cited = {ev.line_no: ev.why for ev in evidence}
    rows = []
    for i, line in enumerate(split_lines(log), start=1):
        hit = i in cited
        style = (
            "background:#fff3bf;color:#1f2328;border-left:4px solid #e0a800;font-weight:600;"
            if hit
            else "border-left:4px solid transparent;"
        )
        title = f' title="{html.escape(cited[i])}"' if hit else ""
        rows.append(
            f'<div style="{style}padding:1px 6px"{title}>'
            f'<span style="opacity:.45;display:inline-block;width:4.5em;text-align:right;'
            f'user-select:none">{i}</span> {html.escape(line)}</div>'
        )
    return (
        '<div style="font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px;'
        "max-height:540px;overflow:auto;white-space:pre;border:1px solid #ddd;border-radius:6px;"
        'padding:6px">' + "".join(rows) + "</div>"
    )


NO_TRACE = "_The rule baseline makes no API calls, so there is no trace._"


def trace_markdown(result: AgentResult | None) -> str:
    if result is None:
        return NO_TRACE
    t = result.totals
    rows = [
        "| step | event | detail | ms |",
        "|---|---|---|---|",
    ]
    for e in result.trace.events:
        if e["kind"] == "llm_call":
            rows.append(
                f"| {e['step']} | LLM `{e['call_mode']}` | {e.get('prompt_tokens')} in / "
                f"{e.get('completion_tokens')} out tokens | {e['latency_ms']:.0f} |"
            )
        elif e["kind"] == "tool_call":
            rows.append(
                f"| {e['step']} | tool `{e['name']}` | "
                f"`{json.dumps(e['args'])[:90]}` → {json.dumps(e['result_summary'])[:120]} | "
                f"{e['latency_ms']:.0f} |"
            )
        elif e["kind"] == "validation":
            errs = "; ".join(e["errors"])[:200] or "passed"
            rows.append(f"| — | validation #{e['attempt']} | {'OK' if e['ok'] else errs} | |")
    summary = (
        f"**{t['api_requests']} API requests** · **{t['total_tokens']:,} tokens** · "
        f"LLM latency {t['llm_latency_ms']:.0f} ms · wall {t['wall_ms']:.0f} ms · "
        f"validation attempts {result.validation_attempts} "
        f"(first try {'passed' if result.valid_first_try else 'failed'})\n\n"
        f"Documents retrieved this run: "
        + (", ".join(f"`{d}`" for d in result.retrieved_doc_ids) or "_none_")
        + "\n\n"
    )
    return summary + "\n".join(rows)


def redaction_markdown(log: str) -> str:
    redacted, r = redact_log(log)
    counts = r.summary()
    kinds = ", ".join(f"**{v}** {k.lower()}" for k, v in sorted(counts.items())) or "nothing"
    head = (
        f"Replaced {kinds} before anything was sent.\n\n"
        "The mapping back to your real values stays in this process — it is never sent to the "
        "model, written to a trace, or logged.\n\n"
    )
    shown = split_lines(redacted)[:400]
    body = "\n".join(f"{i:>5}| {line}" for i, line in enumerate(shown, start=1))
    if len(split_lines(redacted)) > len(shown):
        body += f"\n… ({len(split_lines(redacted)) - len(shown)} more lines)"
    return head + "```\n" + body + "\n```"
