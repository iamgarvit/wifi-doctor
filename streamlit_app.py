"""Streamlit demo for wifi-doctor, for Streamlit Community Cloud.

    streamlit run streamlit_app.py      # from the repository root

The same demo as the Gradio app in ``app.py``: both are thin front ends over
:mod:`wifi_doctor.demo`, which holds the run limits, the call into the agent
and the renderers.

Configuration comes from ``st.secrets`` first, then the environment, then the
demo defaults (``gemini-3.1-flash-lite``, BM25-only retrieval). The API key is
never printed, logged or written anywhere.
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

# Community Cloud installs the dependency file, not this repo as a package.
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from wifi_doctor import demo as core  # noqa: E402


def _secrets() -> dict:
    """The demo settings present in st.secrets, or {} when there is no secrets file."""
    try:
        return {k: st.secrets[k] for k in core.DEMO_SETTING_KEYS if k in st.secrets}
    except Exception:  # noqa: BLE001 - no secrets.toml locally is normal
        return {}


# Before anything reads the settings or builds the knowledge base.
core.apply_demo_settings(_secrets())

from wifi_doctor.config import get_settings  # noqa: E402
from wifi_doctor.retrieval import get_kb  # noqa: E402

EXAMPLES = core.load_examples()
EXAMPLE_KEYS = sorted(EXAMPLES)

INTRO = """\
An LLM agent that reads a `wpa_supplicant` / NetworkManager log and tells you **why** the
Wi-Fi failed — with the exact log lines it used as proof.

Identifiers (MAC addresses, SSIDs, IPs, EAP identities, hostnames) are replaced with
placeholders **before** anything is sent to the model. See *What was sent to the LLM*.
"""


def _init_state() -> None:
    st.session_state.setdefault("runs", 0)
    st.session_state.setdefault("log_text", "")
    st.session_state.setdefault("upload_key", 0)
    st.session_state.setdefault("outcome", None)


def _load_example() -> None:
    name = st.session_state.get("example")
    if name:
        st.session_state.log_text = EXAMPLES[name]
        st.session_state.upload_key += 1  # clears the file uploader


def _read_upload(upload) -> str:
    return upload.getvalue().decode("utf-8", errors="replace")


def _render(outcome: core.Outcome) -> None:
    if outcome.message:
        st.markdown(outcome.message)
    else:
        st.html(core.card_html(outcome.diagnosis, outcome.mode, outcome.notice))

    if not outcome.log:
        return
    tabs = st.tabs(["Log + evidence", "What was sent to the LLM"])
    with tabs[0]:
        if outcome.diagnosis is None:
            st.caption("No diagnosis, so nothing is highlighted.")
            st.html(core.highlighted_log_html(outcome.log, []))
        else:
            st.caption("Highlighted lines are the ones cited as evidence. Hover for why.")
            st.html(core.highlighted_log_html(outcome.log, outcome.diagnosis.evidence))
    with tabs[1]:
        st.markdown(core.redaction_markdown(outcome.log))

    if outcome.diagnosis is not None:
        with st.expander("Trace — tool calls, retrieved docs, latency, tokens"):
            st.markdown(core.trace_markdown(outcome.result))


def main() -> None:
    st.set_page_config(page_title="wifi-doctor", page_icon="📶", layout="wide")
    _init_state()
    settings = get_settings()

    st.title("wifi-doctor")
    st.markdown(INTRO)

    left, right = st.columns([5, 7], gap="large")
    with left:
        st.selectbox(
            "Example logs (one per failure class)",
            EXAMPLE_KEYS,
            index=None,
            placeholder="Pick a synthetic example from the dev split…",
            key="example",
            on_change=_load_example,
        )
        st.text_area(
            "Wi-Fi log",
            key="log_text",
            height=320,
            placeholder="Paste wpa_supplicant / journalctl output here…",
        )
        upload = st.file_uploader(
            "…or upload a log file",
            type=["log", "txt"],
            key=f"upload_{st.session_state.upload_key}",
        )
        mode = st.radio("Mode", list(core.MODES), index=0)
        go = st.button("Diagnose", type="primary", width="stretch")
        st.caption(
            "One agent diagnosis takes about 20–30 s; single-shot takes a few seconds, and the "
            "rule baseline is instant."
        )
        usage = st.empty()

    if go:
        log_text = _read_upload(upload) if upload is not None else st.session_state.log_text
        spinner = (
            "Running the agent… this takes about 20–30 s."
            if core.MODES[mode] == "agent"
            else "Diagnosing…"
        )
        with st.spinner(spinner):
            outcome = core.run(log_text, mode, st.session_state.runs, settings)
        st.session_state.runs += int(outcome.used_run)
        st.session_state.outcome = outcome

    # Filled in after the run so the count includes it.
    usage.caption(
        f"Public demo: {settings.demo_max_runs_per_session} runs per session "
        f"({st.session_state.runs} used), {settings.demo_daily_cap} per day. "
        f"Model: `{settings.model}`, retrieval: `{get_kb().backend}`."
    )

    with right:
        if st.session_state.outcome is None:
            st.info("Pick an example or paste a log, then press **Diagnose**.")
        else:
            _render(st.session_state.outcome)


if __name__ == "__main__":
    main()
