"""Redaction must be total, stable and reversible -- it is the privacy boundary."""

from __future__ import annotations

import re

import pytest

from wifi_doctor.redact import IP_ALLOWLIST, Redactor, redact_log

MAC_PATTERN = re.compile(r"\b(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}\b")


def test_mac_is_replaced_and_stable():
    r = Redactor()
    out = r.redact("assoc with 00:1a:2b:3c:4d:5e then deauth from 00:1a:2b:3c:4d:5e")
    assert out.count("<MAC_1>") == 2
    assert not MAC_PATTERN.search(out)


def test_distinct_macs_get_distinct_placeholders():
    r = Redactor()
    out = r.redact("a 00:11:22:33:44:55 b aa:bb:cc:dd:ee:ff")
    assert "<MAC_1>" in out and "<MAC_2>" in out


def test_mac_case_insensitive_identity():
    r = Redactor()
    out = r.redact("00:1A:2B:3C:4D:5E and 00:1a:2b:3c:4d:5e")
    assert out.count("<MAC_1>") == 2


def test_ssid_keeps_its_quoting():
    r = Redactor()
    assert r.redact("(SSID='HomeNet-5G' freq=2437 MHz)") == "(SSID='<SSID_1>' freq=2437 MHz)"
    assert r.redact('ssid="HomeNet-5G"') == 'ssid="<SSID_1>"'


def test_ipv4_replaced_but_protocol_constants_kept():
    r = Redactor()
    out = r.redact("DHCPOFFER of 192.168.1.42 from 192.168.1.1 to 255.255.255.255")
    assert "192.168" not in out
    assert "255.255.255.255" in out
    for const in IP_ALLOWLIST:
        assert const in Redactor().redact(f"x {const} y")


def test_ipv6_replaced():
    r = Redactor()
    out = r.redact("addr fe80::1c2d:3e4f:5a6b:7c8d on wlan0")
    assert "fe80::" not in out and "<IPV6_1>" in out


def test_eap_identity_and_bare_email_replaced():
    r = Redactor()
    out = r.redact("EAP: Identity response: jdoe@univ.edu")
    assert "jdoe" not in out and "<IDENTITY_1>" in out
    assert "alice" not in Redactor().redact("mail alice.smith@corp.example here")


def test_syslog_username_and_hostname_replaced():
    r = Redactor()
    out = r.redact("Sep 25 19:04:12 thinkpad-t14 systemd-logind: New session 7 of user devuser.")
    assert "thinkpad-t14" not in out and "devuser" not in out
    assert "<HOST_1>" in out and "<IDENTITY_1>" in out


def test_hostname_redaction_can_be_disabled():
    r = Redactor(redact_hostnames=False)
    assert "nuc-lab" in r.redact("Sep 25 19:04:12 nuc-lab kernel: wlan0: associated")


def test_certificate_subject_is_redacted():
    """Regression: an SSID embedded in a RADIUS cert subject used to leak."""
    r = Redactor()
    out = r.redact(
        "CTRL-EVENT-EAP-PEER-CERT depth=0 subject='/CN=radius.corpwifi.example' hash=sha256"
    )
    assert "corpwifi" not in out and "<CERT_1>" in out
    assert r.unredact(out).endswith("hash=sha256")


def test_unredact_is_exact_inverse():
    r = Redactor()
    original = "Sep 25 19:04:12 nuc-lab wpa_supplicant[9]: wlan0: Associated with 00:1a:2b:3c:4d:5e (SSID='Cafe_Guest')"
    assert r.unredact(r.redact(original)) == original


def test_roundtrip_and_line_count_on_every_dev_case(dev_cases):
    for case in dev_cases:
        redacted, r = redact_log(case["log"])
        assert r.unredact(redacted) == case["log"], case["id"]
        assert len(redacted.split("\n")) == case["n_lines"], case["id"]


def test_no_identifiers_survive_on_real_cases(dev_cases):
    for case in dev_cases[:12]:
        redacted, _ = redact_log(case["log"])
        assert not MAC_PATTERN.search(redacted), case["id"]
        assert case["entities"]["ssid"] not in redacted, case["id"]
        assert case["entities"]["host"] not in redacted, case["id"]


def test_mapping_is_not_empty_but_summary_is_countsonly(dev_cases):
    _, r = redact_log(dev_cases[0]["log"])
    assert r.mapping
    assert all(isinstance(v, int) for v in r.summary().values())


@pytest.mark.parametrize("text", ["", "no identifiers here at all", "version 1.2.3.4.5"])
def test_degenerate_inputs(text):
    r = Redactor()
    assert r.unredact(r.redact(text)) == text
