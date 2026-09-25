"""The demo's handlers. Skipped where gradio is not installed (e.g. lean CI)."""

from __future__ import annotations

import pytest

pytest.importorskip("gradio", reason="gradio is not installed in this environment")

import app as demo  # noqa: E402


def test_one_example_per_root_cause():
    from wifi_doctor.schema import ALL_ROOT_CAUSES

    assert len(demo.EXAMPLE_KEYS) == len(ALL_ROOT_CAUSES)
    labels = {k.split("  (")[0] for k in demo.EXAMPLE_KEYS}
    assert labels == set(ALL_ROOT_CAUSES)


def test_loading_an_example_fills_the_box_and_clears_the_upload():
    log, upload = demo.load_example(demo.EXAMPLE_KEYS[0])
    assert log.count("\n") > 10 and upload is None


def test_empty_input_is_refused_politely():
    card, *_ = demo.run_diagnosis("   ", None, "agent (tools + RAG)", 0)
    assert "Paste a log" in card["value"]


def test_long_logs_are_truncated_with_a_notice():
    big = "\n".join(f"Sep 25 19:04:12 host CRON: filler {i}" for i in range(3000))
    log, notice = demo._prepare(big, None)
    assert len(log.split("\n")) == demo.MAX_INPUT_LINES
    assert "3,000 lines" in notice


def test_short_logs_are_untouched():
    log, notice = demo._prepare("a\nb\nc", None)
    assert log == "a\nb\nc" and notice == ""


def test_baseline_mode_needs_no_key_and_produces_a_card(dev_cases):
    case = dev_cases[0]
    card, log_view, trace, redaction, runs = demo.run_diagnosis(
        case["log"], None, "rule baseline (no LLM)", 0
    )
    assert case["root_cause"] in card
    assert "no API calls" in trace
    assert runs == 0, "the baseline must not consume a session run"
    assert "highlight" in log_view or "#fff3bf" in log_view


def test_the_redaction_preview_shows_placeholders_not_identifiers(dev_cases):
    case = dev_cases[0]
    panel = demo._redaction_panel(case["log"])
    assert case["entities"]["ssid"] not in panel
    assert case["entities"]["bssid"] not in panel
    assert "<MAC_1>" in panel and "Replaced" in panel


def test_session_cap_refuses_once_reached():
    settings = demo.get_settings()
    msg = demo._check_quota(settings.demo_max_runs_per_session, settings)
    assert msg and "Session limit reached" in msg
    assert demo._check_quota(0, settings) is None


def test_daily_cap_refuses_once_reached(monkeypatch):
    settings = demo.get_settings()
    monkeypatch.setitem(demo._daily, "date", "")
    assert demo._check_quota(0, settings) is None
    monkeypatch.setitem(demo._daily, "count", settings.demo_daily_cap)
    msg = demo._check_quota(0, settings)
    assert msg and "Daily cap reached" in msg


def test_missing_key_gives_a_friendly_message(dev_cases, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(demo, "get_settings", lambda *a, **k: _NoKey())
    card, *_ = demo.run_diagnosis(dev_cases[0]["log"], None, "agent (tools + RAG)", 0)
    assert "No API key configured" in card["value"]


def test_provider_quota_gives_a_friendly_message(dev_cases, monkeypatch):
    from wifi_doctor.llm import RateLimitError

    def exhausted(*a, **k):
        raise RateLimitError("429 GenerateRequestsPerDayPerProjectPerModel-FreeTier")

    monkeypatch.setattr(demo, "get_settings", lambda *a, **k: _WithKey())
    monkeypatch.setattr(demo.core, "diagnose", exhausted)
    monkeypatch.setitem(demo._daily, "date", "")
    card, _, _, redaction, runs = demo.run_diagnosis(
        dev_cases[0]["log"], None, "agent (tools + RAG)", 0
    )
    assert "Free-tier quota spent" in card["value"]
    assert runs == 0 and redaction


class _NoKey:
    provider = "gemini"
    model = "gemini-3.5-flash-lite"
    has_key = False
    demo_max_runs_per_session = 5
    demo_daily_cap = 100
    rpm = 15
    rpd = 500


def test_evidence_lines_are_highlighted(dev_cases):
    from wifi_doctor.baseline import classify

    case = next(c for c in dev_cases if c["root_cause"] == "WRONG_PASSWORD")
    d = classify(case["log"])
    html = demo._highlighted_log(case["log"], d.evidence)
    assert html.count("#fff3bf") == len(d.evidence)


class _WithKey(_NoKey):
    provider = "mock"
    model = "mock-1"
    has_key = True
