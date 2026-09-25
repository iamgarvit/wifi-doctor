"""Tools must return line-numbered, structured views and never raise at the model."""

from __future__ import annotations

import pytest

from wifi_doctor.redact import redact_log
from wifi_doctor.tools import MAX_HITS_CAP, TOOLS_BY_NAME, ToolContext, dispatch


@pytest.fixture
def ctx(kb, case_by_label):
    redacted, _ = redact_log(case_by_label["WRONG_PASSWORD"]["log"])
    return ToolContext.from_log(redacted, kb)


def test_search_log_returns_real_line_numbers(ctx):
    out = dispatch(ctx, "search_log", {"pattern": "WRONG_KEY", "max_hits": 5})
    assert out["matches"]
    for m in out["matches"]:
        assert "WRONG_KEY" in ctx.redacted_lines[m["line_no"] - 1]


def test_search_log_caps_max_hits(ctx):
    out = dispatch(ctx, "search_log", {"pattern": ".", "max_hits": 9999})
    assert out["returned"] <= MAX_HITS_CAP


def test_search_log_survives_a_broken_regex(ctx):
    out = dispatch(ctx, "search_log", {"pattern": "[unclosed"})
    assert "error" not in out and out["returned"] == 0


def test_get_timeline_reports_states_and_bssids(ctx):
    out = dispatch(ctx, "get_timeline", {})
    assert out["furthest_state"] == "4WAY_HANDSHAKE"
    assert out["states"] and out["control_events"]
    assert out["n_bssids_involved"] >= 1
    assert all(b.startswith("<MAC_") for b in out["bssids_involved"])


def test_get_timeline_sees_two_bssids_for_a_roam(kb, case_by_label):
    redacted, _ = redact_log(case_by_label["ROAMING_FAILURE"]["log"])
    out = dispatch(ToolContext.from_log(redacted, kb), "get_timeline", {})
    assert out["n_bssids_involved"] >= 2


def test_lookup_code_reads_the_kb_tables(ctx):
    r = dispatch(ctx, "lookup_code", {"kind": "reason", "code": 15})
    assert r["found"] and "handshake" in r["meaning"].lower()
    assert "9-49" in r["source"]
    s = dispatch(ctx, "lookup_code", {"kind": "status", "code": 17})
    assert s["found"] and "9-50" in s["source"]


def test_lookup_code_rejects_a_bad_kind_and_unknown_code(ctx):
    assert "error" in dispatch(ctx, "lookup_code", {"kind": "banana", "code": 1})
    miss = dispatch(ctx, "lookup_code", {"kind": "reason", "code": 4242})
    assert miss["found"] is False and miss["known_codes"]


def test_lookup_code_records_the_doc_id_for_citation_checking(ctx):
    dispatch(ctx, "lookup_code", {"kind": "reason", "code": 15})
    assert "reason-codes" in ctx.retrieved_doc_ids


def test_retrieve_kb_records_retrieved_doc_ids(ctx):
    out = dispatch(ctx, "retrieve_kb", {"query": "4-way handshake failed", "k": 3})
    assert out["results"]
    assert {r["doc_id"] for r in out["results"]} <= ctx.retrieved_doc_ids


def test_dispatch_reports_unknown_tools_and_missing_arguments(ctx):
    assert "error" in dispatch(ctx, "no_such_tool", {})
    err = dispatch(ctx, "lookup_code", {"kind": "reason"})
    assert "missing required argument" in err["error"]


def test_dispatch_ignores_unexpected_arguments(ctx):
    out = dispatch(ctx, "get_timeline", {"surprise": 1})
    assert "error" not in out


def test_every_tool_spec_is_wellformed():
    for name, spec in TOOLS_BY_NAME.items():
        assert spec.name == name
        assert spec.description.strip()
        assert spec.parameters["type"] == "object"
        assert set(spec.parameters.get("required", [])) <= set(spec.parameters["properties"])
