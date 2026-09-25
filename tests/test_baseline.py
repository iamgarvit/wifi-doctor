"""The rule baseline: the number the agent has to beat."""

from __future__ import annotations

from wifi_doctor.baseline import classify
from wifi_doctor.logparse import split_lines
from wifi_doctor.schema import Diagnosis, RootCause


def test_returns_a_valid_diagnosis_for_every_dev_case(dev_cases):
    for case in dev_cases:
        d = classify(case["log"])
        assert isinstance(d, Diagnosis)
        Diagnosis.model_validate(d.model_dump())


def test_every_cited_line_exists_and_the_quote_matches(dev_cases):
    for case in dev_cases:
        lines = split_lines(case["log"])
        for ev in classify(case["log"]).evidence:
            assert 1 <= ev.line_no <= len(lines), case["id"]
            assert ev.quote in lines[ev.line_no - 1], (case["id"], ev.line_no)


def test_wrong_key_beats_the_generic_handshake_message():
    """`pre-shared key may be incorrect` alone must not win; WRONG_KEY must."""
    log = "\n".join(
        [
            "wlan0: WPA: EAPOL-Key timeout",
            "wlan0: WPA: 4-Way Handshake failed - pre-shared key may be incorrect",
            'wlan0: CTRL-EVENT-SSID-TEMP-DISABLED id=0 ssid="x" auth_failures=1 duration=10 reason=WRONG_KEY',
        ]
    )
    assert classify(log).root_cause is RootCause.WRONG_PASSWORD


def test_eapol_timeout_without_wrong_key_is_a_handshake_timeout():
    log = "\n".join(
        [
            "wlan0: CTRL-EVENT-SIGNAL-CHANGE above=0 signal=-84 noise=-91 txrate=6000",
            "wlan0: WPA: EAPOL-Key timeout",
            "wlan0: deauthenticated from 00:11:22:33:44:55 (Reason: 15=4WAY_HANDSHAKE_TIMEOUT)",
        ]
    )
    assert classify(log).root_cause is RootCause.HANDSHAKE_TIMEOUT


def test_a_locally_generated_deauth_is_not_an_ap_deauth():
    log = (
        "wlan0: deauthenticating from 00:11:22:33:44:55 by local choice (Reason: 3=DEAUTH_LEAVING)"
    )
    assert classify(log).root_cause is not RootCause.AP_DEAUTH


def test_a_connected_log_with_nothing_else_is_healthy():
    log = "wlan0: CTRL-EVENT-CONNECTED - Connection to 00:11:22:33:44:55 completed [id=0 id_str=]"
    d = classify(log)
    assert d.root_cause is RootCause.HEALTHY and d.evidence == []


def test_an_empty_log_asks_for_more_information():
    d = classify("")
    assert d.root_cause is RootCause.HEALTHY and d.needs_more_info is True


def test_the_baseline_never_cites_the_knowledge_base(dev_cases):
    """It does no retrieval, so any citation would be fabricated."""
    assert all(classify(c["log"]).kb_citations == [] for c in dev_cases)
