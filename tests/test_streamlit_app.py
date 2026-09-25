"""The Streamlit app, driven headlessly. Skipped where streamlit is not installed."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("streamlit", reason="streamlit is not installed in this environment")

from streamlit.testing.v1 import AppTest  # noqa: E402

from wifi_doctor import demo as core  # noqa: E402

APP = Path(__file__).resolve().parents[1] / "streamlit_app.py"

FAKE_KEY = "fake-key-for-tests-0000"


@pytest.fixture
def app(monkeypatch):
    # The app writes its resolved settings into os.environ; monkeypatch puts
    # the real values back afterwards.
    for key in core.DEMO_SETTING_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setitem(core._daily, "date", "")
    at = AppTest.from_file(str(APP), default_timeout=60)
    return at


def _page_text(at: AppTest) -> str:
    parts = [m.value for m in at.markdown] + [c.value for c in at.caption]
    parts += [str(getattr(e, "proto", "")) for e in at.get("html")]
    return "\n".join(parts)


def test_key_comes_from_secrets_and_is_never_shown(app):
    import os

    app.secrets["GEMINI_API_KEY"] = FAKE_KEY
    app.run()
    assert not app.exception
    assert os.environ["GEMINI_API_KEY"] == FAKE_KEY
    assert os.environ["LLM_MODEL"] == "gemini-3.1-flash-lite"
    assert os.environ["WIFI_DOCTOR_EMBEDDINGS"] == "0"
    assert FAKE_KEY not in _page_text(app)
    assert any("gemini-3.1-flash-lite" in c.value for c in app.caption)


def test_key_falls_back_to_the_environment(app, monkeypatch):
    import os

    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    app.run()
    assert not app.exception
    assert os.environ["GEMINI_API_KEY"] == FAKE_KEY


def test_example_then_diagnose_renders_a_card_and_counts_the_run(app):
    app.secrets["LLM_PROVIDER"] = "mock"
    app.secrets["LLM_MODEL"] = "mock-1"
    app.run()
    app.selectbox(key="example").select_index(0).run()
    assert len(app.text_area(key="log_text").value) > 1000
    app.button[0].click().run()
    assert not app.exception
    assert app.session_state.runs == 1
    assert "confidence" in _page_text(app)
    assert app.expander and "Trace" in app.expander[0].label


def test_missing_key_gives_the_friendly_message(app):
    app.run()
    app.selectbox(key="example").select_index(0).run()
    app.button[0].click().run()
    assert not app.exception
    assert "No API key configured" in _page_text(app)
    assert app.session_state.runs == 0
