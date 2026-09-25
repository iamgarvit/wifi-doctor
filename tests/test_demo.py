"""The framework-neutral demo core shared by the Gradio and Streamlit apps."""

from __future__ import annotations

import pytest

from wifi_doctor import demo as core
from wifi_doctor.config import get_settings


@pytest.fixture
def clean_env(monkeypatch):
    """Every demo setting unset; monkeypatch restores the real values afterwards."""
    for key in core.DEMO_SETTING_KEYS:
        monkeypatch.delenv(key, raising=False)
    return monkeypatch


def test_demo_settings_prefer_secrets_then_env_then_defaults(clean_env):
    import os

    clean_env.setenv("GEMINI_API_KEY", "from-env")
    clean_env.setenv("DEMO_DAILY_CAP", "7")
    core.apply_demo_settings({"GEMINI_API_KEY": "from-secrets", "LLM_MODEL": "m-secret"})
    assert os.environ["GEMINI_API_KEY"] == "from-secrets"
    assert os.environ["LLM_MODEL"] == "m-secret"
    assert os.environ["DEMO_DAILY_CAP"] == "7"  # env, no secret
    assert os.environ["WIFI_DOCTOR_EMBEDDINGS"] == "0"  # default
    assert os.environ["LLM_PROVIDER"] == "gemini"  # default


def test_demo_settings_fall_back_to_env_key_and_default_model(clean_env):
    env = {"GEMINI_API_KEY": "from-env"}
    core.apply_demo_settings({"GEMINI_API_KEY": "  ", "DEMO_DAILY_CAP": 12}, env)
    assert env["GEMINI_API_KEY"] == "from-env", "a blank secret must not mask the env var"
    assert env["LLM_MODEL"] == "gemini-3.1-flash-lite"
    assert env["DEMO_DAILY_CAP"] == "12"
    assert env["DEMO_MAX_RUNS_PER_SESSION"] == "5"  # default


def test_demo_settings_leave_an_absent_key_absent(clean_env):
    env: dict[str, str] = {}
    core.apply_demo_settings({}, env)
    assert "GEMINI_API_KEY" not in env
    assert env["DEMO_DAILY_CAP"] == "50"
    assert get_settings(provider="gemini").has_key is False


def test_baseline_run_needs_no_key_and_uses_no_session_run(dev_cases):
    out = core.run(dev_cases[0]["log"], "rule baseline (no LLM)", 0, get_settings("mock"))
    assert out.diagnosis is not None and out.result is None and not out.used_run
    assert core.trace_markdown(out.result) == core.NO_TRACE


def test_agent_run_on_the_mock_provider_counts_one_session_run(dev_cases, monkeypatch):
    monkeypatch.setitem(core._daily, "date", "")
    out = core.run(dev_cases[0]["log"], "agent (tools + RAG)", 0, get_settings("mock"))
    assert out.message is None and out.used_run and out.result is not None
    assert "API requests" in core.trace_markdown(out.result)


def test_empty_log_is_refused_without_a_run():
    out = core.run("  \n ", "agent (tools + RAG)", 0, get_settings("mock"))
    assert out.message and "Paste a log" in out.message and not out.used_run
