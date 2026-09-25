"""End-to-end runs of the whole pipeline against MockProvider -- no network.

These are the tests that would catch a regression in the loop itself: tool
dispatch, the forced final call, validation, the feedback retry, tracing, and
un-redaction of the displayed answer.
"""

from __future__ import annotations

import json

import pytest

from wifi_doctor.agent import MAX_STEPS, AgentResult, diagnose
from wifi_doctor.llm import MockProvider
from wifi_doctor.logparse import split_lines
from wifi_doctor.schema import Diagnosis


@pytest.fixture
def wrong_password(case_by_label) -> dict:
    return case_by_label["WRONG_PASSWORD"]


def run(case, kb, **kw) -> AgentResult:
    return diagnose(case["log"], MockProvider(), kb=kb, trace_enabled=False, **kw)


def test_agent_mode_produces_a_valid_diagnosis(wrong_password, kb):
    res = run(wrong_password, kb)
    assert isinstance(res.diagnosis, Diagnosis)
    assert res.diagnosis.root_cause.value == "WRONG_PASSWORD"
    assert res.valid_first_try and res.validation_errors == []


def test_agent_actually_calls_tools(wrong_password, kb):
    res = run(wrong_password, kb)
    names = [e["name"] for e in res.trace.events if e["kind"] == "tool_call"]
    assert "get_timeline" in names and "search_log" in names and "retrieve_kb" in names


def test_every_returned_citation_verifies_against_the_log(wrong_password, kb):
    res = run(wrong_password, kb)
    lines = split_lines(res.redacted_log)
    assert res.diagnosis.evidence
    for ev in res.diagnosis.evidence:
        assert 1 <= ev.line_no <= len(lines)
        assert ev.quote in lines[ev.line_no - 1]


def test_kb_citations_were_all_actually_retrieved(wrong_password, kb):
    res = run(wrong_password, kb)
    assert set(res.diagnosis.kb_citations) <= set(res.retrieved_doc_ids)


def test_the_model_never_sees_the_real_identifiers(wrong_password, kb):
    res = run(wrong_password, kb)
    assert wrong_password["entities"]["ssid"] not in res.redacted_log
    assert wrong_password["entities"]["bssid"] not in res.redacted_log
    assert "<MAC_1>" in res.redacted_log


def test_display_restores_the_real_identifiers(wrong_password, kb):
    res = run(wrong_password, kb)
    shown = res.display()
    assert "<MAC_" not in " ".join(e.quote for e in shown.evidence)
    # The stored diagnosis itself is untouched; only the display copy is mapped back.
    assert shown is not res.diagnosis


def test_validation_failure_triggers_exactly_one_retry(wrong_password, kb):
    res = diagnose(
        wrong_password["log"], MockProvider(fail_first_validation=True), kb=kb, trace_enabled=False
    )
    attempts = [e for e in res.trace.events if e["kind"] == "validation"]
    assert [e["ok"] for e in attempts] == [False, True]
    assert res.validation_attempts == 2 and res.valid_first_try is False
    assert res.validation_errors == []


def test_single_shot_mode_uses_no_tools(wrong_password, kb):
    res = diagnose(
        wrong_password["log"], MockProvider(), mode="single_shot", kb=kb, trace_enabled=False
    )
    assert res.diagnosis.root_cause.value == "WRONG_PASSWORD"
    assert [e for e in res.trace.events if e["kind"] == "tool_call"] == []
    assert res.retrieved_doc_ids == []


def test_unknown_mode_is_rejected(wrong_password, kb):
    with pytest.raises(ValueError, match="single_shot"):
        diagnose(wrong_password["log"], MockProvider(), mode="banana", kb=kb, trace_enabled=False)


def test_step_budget_is_respected(wrong_password, kb):
    res = diagnose(wrong_password["log"], MockProvider(), kb=kb, max_steps=2, trace_enabled=False)
    assert res.steps <= 2 + 1  # tool steps, plus the forced final call
    assert isinstance(res.diagnosis, Diagnosis)


def test_healthy_log_is_not_given_a_fault(case_by_label, kb):
    res = run(case_by_label["HEALTHY"], kb)
    assert res.diagnosis.root_cause.value == "HEALTHY"


def test_trace_is_written_as_jsonl_and_totals_add_up(wrong_password, kb, tmp_path):
    res = diagnose(
        wrong_password["log"], MockProvider(), kb=kb, trace_dir=tmp_path, trace_name="case1"
    )
    path = tmp_path / "case1.jsonl"
    assert path.exists()
    events = [json.loads(line) for line in path.read_text().splitlines()]
    assert events[0]["kind"] == "run_start" and events[-1]["kind"] == "run_end"
    assert all("t_ms" in e and "run_id" in e for e in events)
    llm = [e for e in events if e["kind"] == "llm_call"]
    assert res.totals["api_requests"] == len(llm)
    assert res.totals["total_tokens"] == sum(e["total_tokens"] for e in llm)


def test_trace_never_records_the_redaction_mapping(wrong_password, kb, tmp_path):
    diagnose(wrong_password["log"], MockProvider(), kb=kb, trace_dir=tmp_path, trace_name="c")
    blob = (tmp_path / "c.jsonl").read_text()
    assert wrong_password["entities"]["ssid"] not in blob
    assert wrong_password["entities"]["bssid"] not in blob
    assert wrong_password["entities"]["host"] not in blob


def test_runs_on_every_dev_case_without_raising(dev_cases, kb):
    for case in dev_cases[:12]:
        res = run(case, kb)
        assert isinstance(res.diagnosis, Diagnosis), case["id"]
        assert res.steps <= MAX_STEPS + 1
