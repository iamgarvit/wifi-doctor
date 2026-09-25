"""The guardrail: a citation is only accepted if it can be checked against the log."""

from __future__ import annotations

from wifi_doctor.agent import validate

LINES = [
    "Sep 25 19:04:12 <HOST_1> wpa_supplicant[9]: wlan0: State: ASSOCIATED -> 4WAY_HANDSHAKE",
    "Sep 25 19:04:13 <HOST_1> wpa_supplicant[9]: wlan0: WPA: 4-Way Handshake failed - pre-shared key may be incorrect",
    'Sep 25 19:04:13 <HOST_1> wpa_supplicant[9]: wlan0: CTRL-EVENT-SSID-TEMP-DISABLED id=0 ssid="<SSID_1>" auth_failures=1 duration=10 reason=WRONG_KEY',
]
RETRIEVED = {"troubleshoot-wrong-password", "reason-codes"}


def payload(**over) -> dict:
    base = {
        "root_cause": "WRONG_PASSWORD",
        "summary": "The passphrase is wrong.",
        "evidence": [{"line_no": 3, "quote": "reason=WRONG_KEY", "why": "explicit verdict"}],
        "confidence": 0.9,
        "suggested_fixes": ["Re-enter the passphrase."],
        "kb_citations": ["troubleshoot-wrong-password"],
        "needs_more_info": False,
    }
    return base | over


def test_good_payload_passes():
    d, errors = validate(payload(), LINES, RETRIEVED)
    assert d is not None and errors == []


def test_accepts_a_json_string_too():
    import json

    d, errors = validate(json.dumps(payload()), LINES, RETRIEVED)
    assert d is not None and errors == []


def test_rejects_unparseable_json():
    d, errors = validate("{not json", LINES, RETRIEVED)
    assert d is None and "not valid JSON" in errors[0]


def test_rejects_a_line_number_past_the_end():
    d, errors = validate(
        payload(evidence=[{"line_no": 999, "quote": "x", "why": "y"}]), LINES, RETRIEVED
    )
    assert d is None
    assert "outside the log" in errors[0] and "1..3" in errors[0]


def test_rejects_a_line_number_of_zero():
    d, errors = validate(
        payload(evidence=[{"line_no": 0, "quote": "x", "why": "y"}]), LINES, RETRIEVED
    )
    assert d is None and "outside the log" in errors[0]


def test_rejects_a_quote_that_is_not_on_the_cited_line():
    d, errors = validate(
        payload(evidence=[{"line_no": 1, "quote": "reason=WRONG_KEY", "why": "y"}]),
        LINES,
        RETRIEVED,
    )
    assert d is None
    assert "does not occur on line 1" in errors[0]
    # The error quotes the real line, so the retry can be specific.
    assert "4WAY_HANDSHAKE" in errors[0]


def test_quote_matching_tolerates_whitespace_and_case():
    d, errors = validate(
        payload(evidence=[{"line_no": 2, "quote": "WPA:   4-Way   HANDSHAKE failed", "why": "y"}]),
        LINES,
        RETRIEVED,
    )
    assert d is not None, errors


def test_rejects_a_kb_citation_that_was_never_retrieved():
    d, errors = validate(payload(kb_citations=["invented-doc"]), LINES, RETRIEVED)
    assert d is None
    assert "was not retrieved in this run" in errors[0]


def test_rejects_a_failure_verdict_with_no_evidence():
    d, errors = validate(payload(evidence=[]), LINES, RETRIEVED)
    assert d is None and "no evidence was cited" in errors[0]


def test_allows_healthy_with_no_evidence():
    d, errors = validate(
        payload(root_cause="HEALTHY", evidence=[], kb_citations=[]), LINES, RETRIEVED
    )
    assert d is not None and errors == []


def test_reports_every_problem_at_once_so_one_retry_can_fix_them_all():
    d, errors = validate(
        payload(
            evidence=[
                {"line_no": 999, "quote": "a", "why": "b"},
                {"line_no": 1, "quote": "nope", "why": "b"},
            ],
            kb_citations=["invented-doc"],
        ),
        LINES,
        RETRIEVED,
    )
    assert d is None and len(errors) == 3
