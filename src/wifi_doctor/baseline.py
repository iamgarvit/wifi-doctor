"""Rule-based baseline classifier -- the non-LLM comparison point.

This is deliberately a *good-faith* baseline, not a strawman: the rules encode
the same disambiguations a competent engineer would write after reading
wpa_supplicant output for a week (WRONG_KEY before EAPOL timeout, roam attempt
before generic assoc-reject, and so on). If the agent cannot beat this, the
agent is not worth its API calls -- which is the point of measuring it.

It returns a full :class:`Diagnosis` so evidence precision/recall and schema
validity are computed the same way for every mode.
"""

from __future__ import annotations

from .logparse import find, min_signal, split_lines
from .schema import Diagnosis, Evidence, RootCause

# (label, regex, confidence). Order is significance order: the first rule that
# fires wins, so the most specific signals must come first.
RULES: list[tuple[RootCause, str, float]] = [
    (RootCause.WRONG_PASSWORD, r"reason=WRONG_KEY|pre-shared key may be incorrect", 0.90),
    (RootCause.EAP_FAILURE, r"CTRL-EVENT-EAP-FAILURE|Reason:\s*23=", 0.85),
    (RootCause.HANDSHAKE_TIMEOUT, r"EAPOL-Key timeout|Reason:\s*15=4WAY_HANDSHAKE_TIMEOUT", 0.80),
    (RootCause.AUTH_TIMEOUT, r"[Aa]uthentication with [0-9a-f:]+ timed out", 0.80),
    (RootCause.NETWORK_NOT_FOUND, r"CTRL-EVENT-NETWORK-NOT-FOUND", 0.85),
    (RootCause.DHCP_TIMEOUT, r"No DHCPOFFERS received|dhcp4 \(\w+\): state changed no lease", 0.85),
    (RootCause.ASSOC_REJECTED, r"CTRL-EVENT-ASSOC-REJECT", 0.70),
    (
        RootCause.BEACON_LOSS_WEAK_SIGNAL,
        r"CTRL-EVENT-BEACON-LOSS|Connection to AP [0-9a-f:]+ lost",
        0.70,
    ),
    (RootCause.AP_DEAUTH, r"deauthenticated from [0-9a-f:]+ \(Reason:", 0.60),
]

FIXES: dict[RootCause, list[str]] = {
    RootCause.WRONG_PASSWORD: [
        "Re-enter the network passphrase.",
        "Forget and re-add the network.",
    ],
    RootCause.HANDSHAKE_TIMEOUT: [
        "Move closer to the AP.",
        "Retry; check for interference on this channel.",
    ],
    RootCause.AUTH_TIMEOUT: [
        "Check the AP is reachable and not overloaded.",
        "Retry on a different band.",
    ],
    RootCause.ASSOC_REJECTED: [
        "Look up the association status code.",
        "Try a different AP in the ESS.",
    ],
    RootCause.AP_DEAUTH: [
        "Check the deauth reason code.",
        "Check AP client limits and idle timeouts.",
    ],
    RootCause.EAP_FAILURE: [
        "Verify enterprise username/password.",
        "Check the CA certificate configuration.",
    ],
    RootCause.DHCP_TIMEOUT: [
        "Check the DHCP server / pool exhaustion.",
        "Try a static IP to confirm L2 is fine.",
    ],
    RootCause.BEACON_LOSS_WEAK_SIGNAL: [
        "Move closer to the AP.",
        "Add an AP or extender for coverage.",
    ],
    RootCause.ROAMING_FAILURE: [
        "Check 802.11r/k/v config across APs.",
        "Pin the client to one BSS to confirm.",
    ],
    RootCause.NETWORK_NOT_FOUND: [
        "Confirm the SSID is broadcasting.",
        "Check the band/channel is supported.",
    ],
    RootCause.HEALTHY: [],
}

_ROAM_RE = r"Considering within-ESS reassociation"
_CONNECTED_RE = r"CTRL-EVENT-CONNECTED"


def _evidence(lines: list[str], pattern: str, why: str, limit: int = 4) -> list[Evidence]:
    out = []
    for line_no, text in find(lines, pattern, max_hits=limit):
        # Quote the message body, not the syslog prefix -- shorter and still
        # an exact substring of the line, which the evidence check requires.
        quote = text.split(": ", 2)[-1] if ": " in text else text
        out.append(Evidence(line_no=line_no, quote=quote, why=why))
    return out


def classify(log: str) -> Diagnosis:
    """Diagnose a log using regex rules only. Never calls an LLM."""
    lines = split_lines(log)

    # Roaming is a *sequence*, not a single line: a reassociation decision
    # followed by a failure on the new BSS. Checked before the generic rules so
    # it is not swallowed by ASSOC_REJECTED.
    roam = find(lines, _ROAM_RE, max_hits=1)
    if roam:
        after = [
            (n, t)
            for n, t in find(lines, r"CTRL-EVENT-ASSOC-REJECT|timed out", max_hits=5)
            if n > roam[0][0]
        ]
        if after:
            ev = [
                Evidence(
                    line_no=roam[0][0],
                    quote=roam[0][1].split(": ", 2)[-1],
                    why="Supplicant decided to roam to a different BSS.",
                )
            ]
            ev += [
                Evidence(
                    line_no=n,
                    quote=t.split(": ", 2)[-1],
                    why="The roam target rejected or ignored the client.",
                )
                for n, t in after[:2]
            ]
            return _build(
                RootCause.ROAMING_FAILURE,
                ev,
                0.65,
                "A roam to a better BSS was attempted and failed, dropping the session.",
            )

    for label, pattern, conf in RULES:
        hits = find(lines, pattern, max_hits=1)
        if not hits:
            continue
        if label is RootCause.AP_DEAUTH and find(lines, r"by local choice", max_hits=1):
            # A locally generated deauth is the client leaving, not the AP kicking us.
            continue
        ev = _evidence(lines, pattern, f"Matches the {label.value} signature.")
        summary = f"Rule match for {label.value}."
        if label is RootCause.HANDSHAKE_TIMEOUT and (sig := min_signal(lines)) is not None:
            summary += f" Weakest observed signal {sig} dBm."
        return _build(label, ev, conf, summary)

    if find(lines, _CONNECTED_RE, max_hits=1):
        return _build(
            RootCause.HEALTHY,
            [],
            0.75,
            "The client reached CTRL-EVENT-CONNECTED and no failure signature matched.",
        )
    return _build(
        RootCause.HEALTHY,
        [],
        0.35,
        "No failure signature matched, but no successful connection was observed either.",
        needs_more_info=True,
    )


def _build(
    label: RootCause, ev: list[Evidence], conf: float, summary: str, needs_more_info: bool = False
) -> Diagnosis:
    return Diagnosis(
        root_cause=label,
        summary=summary,
        evidence=ev,
        confidence=conf,
        suggested_fixes=FIXES[label],
        kb_citations=[],  # the baseline does no retrieval, by construction
        needs_more_info=needs_more_info,
    )


__all__: list[str] = ["classify", "RULES", "FIXES"]
