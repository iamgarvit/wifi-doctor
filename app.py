"""Gradio demo for wifi-doctor, deployable to a Hugging Face Space. Needs no GPU.

The demo logic (limits, the call into the agent, the renderers) lives in
:mod:`wifi_doctor.demo` and is shared with the Streamlit app; this file is only
the Gradio layout and the glue from its widgets to that module.

The "what was sent to the LLM" tab is not decoration. It is the demonstrable
claim of this project: the operator can see, for their own log, exactly which
bytes left the machine.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import gradio as gr

# Hugging Face Spaces runs `app.py` against requirements.txt without installing
# this repo as a package, so make `src/` importable before anything else.
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from wifi_doctor import demo as core
from wifi_doctor.config import get_settings
from wifi_doctor.retrieval import get_kb

MAX_INPUT_LINES = core.MAX_INPUT_LINES
EXAMPLES = core.load_examples()
EXAMPLE_KEYS = sorted(EXAMPLES)

# Kept under their historical names; the implementations live in wifi_doctor.demo.
_daily = core._daily
_check_quota = core.check_quota
_card = core.card_html
_highlighted_log = core.highlighted_log_html
_trace_panel = core.trace_markdown
_redaction_panel = core.redaction_markdown


def _prepare(log_text: str, file_obj) -> tuple[str, str]:
    """Return (log, notice). Reads the upload if one was given."""
    if file_obj is not None:
        try:
            log_text = Path(file_obj.name if hasattr(file_obj, "name") else file_obj).read_text(
                errors="replace"
            )
        except OSError as exc:
            return "", f"Could not read the uploaded file: {exc}"
    return core.prepare(log_text)


# --------------------------------------------------------------------------
# the handler
# --------------------------------------------------------------------------


def run_diagnosis(log_text, file_obj, mode, session_runs):
    log, notice = _prepare(log_text, file_obj)
    if not log:
        return gr.update(value=f"### {notice}"), "", "", "", session_runs

    out = core.run(log, mode, session_runs, get_settings())
    if out.message:
        return gr.update(value=out.message), "", "", _redaction_panel(out.log), session_runs
    return (
        _card(out.diagnosis, out.mode, out.notice or notice),
        _highlighted_log(out.log, out.diagnosis.evidence),
        _trace_panel(out.result),
        _redaction_panel(out.log),
        session_runs + int(out.used_run),
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
                    list(core.MODES),
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
