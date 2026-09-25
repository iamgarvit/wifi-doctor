"""Replace identifiers with stable placeholders before any text leaves the box.

Why this exists: the free tiers of both providers this project targets reserve
the right to use submitted prompts to improve their products. A Wi-Fi log is
not neutral data — a BSSID plus an SSID is a geolocatable fingerprint (that is
exactly how public BSSID-to-location databases work), and an EAP identity is a
username. So nothing identifying is sent at all.

The mapping is kept **in the process only**, never written to a trace or a
file, and is used to put the real values back for display. Placeholders are
assigned in order of first appearance and are stable within one document, so
the model can still reason about "the same AP as before" -- which is most of
what the identifiers are actually for.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Order matters: MACs are matched before IPv6, because both are colon-separated
# hex and a MAC would otherwise be swallowed by a loose IPv6 pattern.
MAC_RE = re.compile(r"\b(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}\b")
IPV6_RE = re.compile(
    r"\b(?:[0-9a-fA-F]{1,4}:){1,7}:[0-9a-fA-F]{0,4}(?::[0-9a-fA-F]{1,4}){0,6}\b"
    r"|\b(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}\b"
)
IPV4_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
# SSIDs only ever appear quoted in supplicant output; anything else would be a
# guess, and guessing here means either leaking or mangling the log.
SSID_RE = re.compile(r"(?i)\b(ssid=)(['\"])(.*?)\2")
IDENTITY_RE = re.compile(
    r"(?i)((?:EAP:\s*Identity response:|identity=|anonymous_identity=|user=|(?:of|for)\s+user)\s*['\"]?)"
    r"([A-Za-z0-9._%+\-]+(?:@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})?)"
)
EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")
# `Mon DD HH:MM:SS <host> proc[pid]:` -- the third syslog field is the device name.
SYSLOG_HOST_RE = re.compile(r"^([A-Z][a-z]{2} [ \d]\d \d{2}:\d{2}:\d{2} )([^\s]+)(\s)")

PLACEHOLDER_RE = re.compile(r"<(MAC|SSID|IPV4|IPV6|IDENTITY|HOST)_(\d+)>")

# Addresses that are protocol constants, not anybody's address. Redacting these
# would destroy meaning (a DHCPDISCOVER *must* go to 255.255.255.255) and
# protect nothing.
IP_ALLOWLIST = {"0.0.0.0", "255.255.255.255", "127.0.0.1", "::1", "::"}


@dataclass
class Redactor:
    """Stateful, per-document redactor. One instance per log.

    >>> r = Redactor()
    >>> r.redact("assoc with 00:1a:2b:3c:4d:5e (SSID='HomeNet')")
    "assoc with <MAC_1> (SSID='<SSID_1>')"
    >>> r.unredact("The AP <MAC_1> rejected us.")
    'The AP 00:1a:2b:3c:4d:5e rejected us.'
    """

    redact_hostnames: bool = True
    _forward: dict[str, str] = field(default_factory=dict)  # real value -> placeholder
    _reverse: dict[str, str] = field(default_factory=dict)  # placeholder -> real value
    _counts: dict[str, int] = field(default_factory=dict)  # kind -> next index

    # -- internals ---------------------------------------------------------
    def _placeholder(self, kind: str, value: str) -> str:
        key = f"{kind}\x00{value.lower() if kind in {'MAC', 'IPV6'} else value}"
        if key in self._forward:
            return self._forward[key]
        idx = self._counts.get(kind, 0) + 1
        self._counts[kind] = idx
        token = f"<{kind}_{idx}>"
        self._forward[key] = token
        self._reverse[token] = value
        return token

    @staticmethod
    def _is_ipv4(s: str) -> bool:
        parts = s.split(".")
        return len(parts) == 4 and all(
            p.isdigit() and 0 <= int(p) <= 255 and (p == "0" or not p.startswith("0"))
            for p in parts
        )

    # -- public API --------------------------------------------------------
    def redact(self, text: str) -> str:
        """Return ``text`` with every identifier replaced by a stable placeholder."""
        if self.redact_hostnames:
            text = "\n".join(
                SYSLOG_HOST_RE.sub(
                    lambda m: m.group(1) + self._placeholder("HOST", m.group(2)) + m.group(3), line
                )
                for line in text.split("\n")
            )
        text = MAC_RE.sub(lambda m: self._placeholder("MAC", m.group(0)), text)
        text = SSID_RE.sub(
            lambda m: (
                m.group(1) + m.group(2) + self._placeholder("SSID", m.group(3)) + m.group(2)
                if m.group(3)
                else m.group(0)
            ),
            text,
        )
        text = IDENTITY_RE.sub(
            lambda m: m.group(1) + self._placeholder("IDENTITY", m.group(2)), text
        )
        text = EMAIL_RE.sub(lambda m: self._placeholder("IDENTITY", m.group(0)), text)
        text = IPV6_RE.sub(
            lambda m: (
                m.group(0)
                if m.group(0) in IP_ALLOWLIST or PLACEHOLDER_RE.search(m.group(0))
                else self._placeholder("IPV6", m.group(0))
            ),
            text,
        )
        text = IPV4_RE.sub(
            lambda m: (
                m.group(0)
                if (m.group(0) in IP_ALLOWLIST or not self._is_ipv4(m.group(0)))
                else self._placeholder("IPV4", m.group(0))
            ),
            text,
        )
        return text

    def unredact(self, text: str) -> str:
        """Put the real values back, for display to the person who owns the log."""
        return PLACEHOLDER_RE.sub(lambda m: self._reverse.get(m.group(0), m.group(0)), text)

    @property
    def mapping(self) -> dict[str, str]:
        """placeholder -> original value. Never persist this."""
        return dict(self._reverse)

    def summary(self) -> dict[str, int]:
        """How many distinct values of each kind were replaced. Safe to log."""
        return dict(self._counts)


def redact_log(log: str, *, redact_hostnames: bool = True) -> tuple[str, Redactor]:
    """Convenience wrapper: returns ``(redacted_text, redactor)``."""
    r = Redactor(redact_hostnames=redact_hostnames)
    return r.redact(log), r
