"""Gradio demo for wifi-doctor, deployable to a Hugging Face Space. Needs no GPU.

Public-demo discipline lives in :func:`_check_quota`: a per-session run cap and
a process-wide daily cap, both configurable, plus a friendly message instead of
a stack trace when the API key is missing or the quota is spent.

The "what was sent to the LLM" tab is not decoration. It is the demonstrable
claim of this project: the operator can see, for their own log, exactly which
bytes left the machine.
"""

from __future__ import annotations

import html
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import gradio as gr

# Hugging Face Spaces runs `app.py` against requirements.txt without installing
# this repo as a package, so make `src/` importable before anything else.
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from wifi_doctor.agent import diagnose
from wifi_doctor.baseline import classify
from wifi_doctor.config import ROOT, get_settings
from wifi_doctor.llm import ProviderError, RateLimitError, build_provider
from wifi_doctor.logparse import split_lines, truncate_for_prompt
from wifi_doctor.ratelimit import DailyQuotaExceeded, RateLimiter
from wifi_doctor.redact import redact_log
from wifi_doctor.retrieval import get_kb
from wifi_doctor.schema import RootCause

MAX_INPUT_LINES = 2000
EXAMPLES_PATH = ROOT / "data" / "synthetic" / "dev" / "cases.jsonl"

# Process-wide daily cap. A Space restarts occasionally, which resets this; it
# is a courtesy limit on a free key, not a billing control.
_daily = {"date": "", "count": 0}


def _load_examples() -> dict[str, str]:
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


EXAMPLES = _load_examples()
EXAMPLE_KEYS = sorted(EXAMPLES)


def _check_quota(session_runs: int, settings) -> str | None:
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
    if _daily["date"] != today:
        _daily.update(date=today, count=0)
    if _daily["count"] >= settings.demo_daily_cap:
        return (
            f"### Daily cap reached\n\nThis Space has used its **{settings.demo_daily_cap} "
            f"diagnoses for today** (UTC). Please come back tomorrow, or clone the Space and "
            f"add your own free Gemini API key. The **rule baseline** mode still works."
        )
    return None


def _prepare(log_text: str, file_obj) -> tuple[str, str]:
    """Return (log, notice). Reads the upload if one was given."""
    if file_obj is not None:
        try:
            log_text = Path(file_obj.name if hasattr(file_obj, "name") else file_obj).read_text(
                errors="replace"
            )
        except OSError as exc:
            return "", f"Could not read the uploaded file: {exc}"
    log_text = (log_text or "").strip("\n")
    if not log_text.strip():
        return "", "Paste a log, upload a file, or pick an example."
    lines = split_lines(log_text)
    if len(lines) <= MAX_INPUT_LINES:
        return log_text, ""
    nums, kept = truncate_for_prompt(lines, MAX_INPUT_LINES)
    notice = (
        f"Log is {len(lines):,} lines; trimmed to {len(kept):,} for the demo, keeping the "
        f"lines around every state change and control event. Line numbers below are "
        f"renumbered against the trimmed log."
    )
    return "\n".join(kept), notice


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------

_SEVERITY = {RootCause.HEALTHY: ("#0f7b30", "#e8f6ec", "No fault found")}


def _card(diagnosis, mode: str, notice: str) -> str:
    healthy = diagnosis.root_cause is RootCause.HEALTHY
    colour, bg, _ = _SEVERITY.get(diagnosis.root_cause, ("#a8331a", "#fdeeea", "Failure"))
    conf = f"{diagnosis.confidence:.0%}"
    bits = [
        f'<div style="border-left:6px solid {colour};background:{bg};padding:14px 16px;'
        f'border-radius:6px;margin-bottom:12px">',
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


def _highlighted_log(log: str, evidence) -> str:
    cited = {ev.line_no: ev.why for ev in evidence}
    rows = []
    for i, line in enumerate(split_lines(log), start=1):
        hit = i in cited
        style = (
            "background:#fff3bf;border-left:4px solid #e0a800;font-weight:600;"
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


def _trace_panel(result) -> str:
    if result is None:
        return "_The rule baseline makes no API calls, so there is no trace._"
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


def _redaction_panel(log: str) -> str:
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


# --------------------------------------------------------------------------
# the handler
# --------------------------------------------------------------------------


def run_diagnosis(log_text, file_obj, mode, session_runs):
    settings = get_settings()
    log, notice = _prepare(log_text, file_obj)
    if not log:
        return gr.update(value=f"### {notice}"), "", "", "", session_runs

    if mode == "rule baseline (no LLM)":
        d = classify(log)
        return (
            _card(d, "baseline", notice),
            _highlighted_log(log, d.evidence),
            "_The rule baseline makes no API calls, so there is no trace._",
            _redaction_panel(log),
            session_runs,
        )

    if not settings.has_key:
        return (
            gr.update(
                value=(
                    "### No API key configured\n\nThis Space needs a `GEMINI_API_KEY` secret "
                    "(Settings → Variables and secrets). Get a free key at "
                    "[aistudio.google.com/apikey](https://aistudio.google.com/apikey).\n\n"
                    "Meanwhile, the **rule baseline** mode works with no key at all."
                )
            ),
            "",
            "",
            _redaction_panel(log),
            session_runs,
        )

    if refusal := _check_quota(session_runs, settings):
        return gr.update(value=refusal), "", "", _redaction_panel(log), session_runs

    limiter = RateLimiter(settings.provider, settings.rpm, settings.rpd)
    try:
        provider = build_provider(settings, rate_limiter=limiter)
        result = diagnose(
            log,
            provider,
            mode="agent" if mode.startswith("agent") else "single_shot",
            kb=get_kb(),
            trace_enabled=False,
        )
    except (DailyQuotaExceeded, RateLimitError):
        # Either the local daily budget (LLM_RPD) or the provider's own quota,
        # which the provider layer gives up on without a long backoff.
        return (
            gr.update(
                value=(
                    "### Free-tier quota spent\n\nThe model's free daily request quota is "
                    "used up, or the provider is rate-limiting this Space. Try again later, "
                    "or use the **rule baseline** mode, which needs no API access."
                )
            ),
            "",
            "",
            _redaction_panel(log),
            session_runs,
        )
    except ProviderError as exc:
        return (
            gr.update(value=f"### The model provider returned an error\n\n```\n{exc}\n```"),
            "",
            "",
            _redaction_panel(log),
            session_runs,
        )

    _daily["count"] += 1
    shown = result.display()
    return (
        _card(shown, result.mode, notice),
        _highlighted_log(log, shown.evidence),
        _trace_panel(result),
        _redaction_panel(log),
        session_runs + 1,
    )


def load_example(name):
    return EXAMPLES.get(name, ""), None


INTRO = """\
# wifi-doctor

An LLM agent that reads a `wpa_supplicant` / NetworkManager log and tells you **why** the
Wi-Fi failed — with the exact log lines it used as proof.

Identifiers (MAC addresses, SSIDs, IPs, EAP identities, hostnames) are replaced with
placeholders **before** anything is sent to the model. See the *What was sent to the LLM* tab.
"""


def build_ui() -> gr.Blocks:
    settings = get_settings()
    with gr.Blocks(title="wifi-doctor") as demo:
        session_runs = gr.State(0)
        gr.Markdown(INTRO)
        with gr.Row():
            with gr.Column(scale=5):
                example = gr.Dropdown(
                    EXAMPLE_KEYS,
                    label="Example logs (one per failure class)",
                    info="Synthetic, from the dev split.",
                )
                log_box = gr.Textbox(
                    label="Wi-Fi log",
                    lines=16,
                    max_lines=16,
                    placeholder="Paste wpa_supplicant / journalctl output here…",
                )
                upload = gr.File(label="…or upload a log file", file_types=[".log", ".txt"])
                mode = gr.Radio(
                    [
                        "agent (tools + RAG)",
                        "single-shot (whole log, one prompt)",
                        "rule baseline (no LLM)",
                    ],
                    value="agent (tools + RAG)",
                    label="Mode",
                )
                go = gr.Button("Diagnose", variant="primary")
                gr.Markdown(
                    f"<sub>Public demo: {settings.demo_max_runs_per_session} runs per session, "
                    f"{settings.demo_daily_cap} per day. Model: "
                    f"<code>{settings.model}</code>, retrieval: "
                    f"<code>{get_kb().backend}</code>.</sub>"
                )
            with gr.Column(scale=7), gr.Tabs():
                with gr.Tab("Diagnosis"):
                    card = gr.HTML()
                with gr.Tab("Log + evidence"):
                    gr.Markdown(
                        "<sub>Highlighted lines are the ones the model cited. "
                        "Hover for its reasoning.</sub>"
                    )
                    log_view = gr.HTML()
                with gr.Tab("Trace"):
                    trace_view = gr.Markdown()
                with gr.Tab("What was sent to the LLM"):
                    redaction_view = gr.Markdown()

        example.change(load_example, example, [log_box, upload])
        go.click(
            run_diagnosis,
            [log_box, upload, mode, session_runs],
            [card, log_view, trace_view, redaction_view, session_runs],
        )
    return demo


if __name__ == "__main__":
    build_ui().launch(
        theme=gr.themes.Soft(),
        server_name=os.environ.get("GRADIO_SERVER_NAME", "127.0.0.1"),
        server_port=int(os.environ.get("GRADIO_SERVER_PORT", "7860")),
    )
