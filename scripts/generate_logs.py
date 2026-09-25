#!/usr/bin/env python3
"""Generate synthetic wpa_supplicant / NetworkManager-style connection logs.

Every case carries ground truth: a single ``root_cause`` label and the exact
1-based line numbers of the lines that justify it. Those line numbers are
recorded at emit time (not recovered by grepping afterwards), so they stay
correct no matter how much noise is interleaved.

The log *format* is modelled on real wpa_supplicant/kernel/dhclient output --
only control-event names, state names, reason codes and status codes that
actually exist are used (see ``data/README.md``). The *content* is invented.

Usage::

    python scripts/generate_logs.py --out data/synthetic
"""

from __future__ import annotations

import argparse
import json
import random
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

# --------------------------------------------------------------------------
# entity pools
# --------------------------------------------------------------------------

SSIDS = [
    "HomeNet-5G",
    "Cafe_Guest",
    "eduroam",
    "CorpWiFi",
    "Starbucks",
    "TP-Link_4A2C",
    "Airport_Free_WiFi",
    "NETGEAR72",
    "Pixel_1234",
    "MyFiberNet",
    "Hotel-Guest",
    "Lab-Wireless",
    "ATT8xQz2",
    "Xfinity",
    "OfficeNet-Guest",
]
HOSTS = ["laptop-01", "thinkpad-t14", "dev-box", "mbp-linux", "nuc-lab", "x1carbon"]
OUIS = ["00:1a:2b", "ac:9e:17", "3c:37:86", "f8:32:e4", "74:83:c2", "b0:be:76", "e0:cc:f8"]
FREQS_24 = [2412, 2417, 2422, 2437, 2442, 2452, 2462]
FREQS_5 = [5180, 5200, 5220, 5240, 5745, 5765, 5785, 5805]
EAP_IDENTITIES = [
    "jdoe@univ.edu",
    "alice.smith@corp.example",
    "s1234567@student.ac.uk",
    "bob@eng.example.com",
    "m.garcia@company.net",
]

VARIANTS = ["plain", "heavy_noise", "misleading", "truncated", "transient_recovery"]
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _mac(rng: random.Random) -> str:
    return (
        f"{rng.choice(OUIS)}:{rng.randint(0, 255):02x}"
        f":{rng.randint(0, 255):02x}:{rng.randint(0, 255):02x}"
    )


def _ipv4(rng: random.Random) -> tuple[str, str]:
    """Return (client_ip, gateway_ip) from a plausible private subnet."""
    third = rng.choice([0, 1, 2, 10, 43, 88])
    gw = f"192.168.{third}.1"
    return f"192.168.{third}.{rng.randint(20, 240)}", gw


# --------------------------------------------------------------------------
# emitter
# --------------------------------------------------------------------------


@dataclass
class Emitter:
    """Accumulates syslog lines and remembers which ones are ground-truth evidence."""

    rng: random.Random
    host: str
    iface: str = "wlan0"
    lines: list[str] = field(default_factory=list)
    evidence: list[int] = field(default_factory=list)
    t: datetime = field(default_factory=lambda: datetime(2025, 9, 25, 19, 4, 12))
    wpa_pid: int = 1123
    nm_pid: int = 812
    dh_pid: int = 1517

    def _stamp(self, advance_ms: int) -> str:
        self.t += timedelta(milliseconds=advance_ms)
        # strftime("%b") is locale-dependent, which would make the generated
        # corpus differ between machines. CI checks the dataset regenerates
        # byte-identically, so the month name is spelled out here instead.
        return (
            f"{MONTHS[self.t.month - 1]} {self.t.day:02d} "
            f"{self.t.hour:02d}:{self.t.minute:02d}:{self.t.second:02d}"
        )

    def emit(self, source: str, text: str, *, ev: bool = False, gap: int | None = None) -> int:
        """Append one line. Returns its 1-based line number."""
        ms = gap if gap is not None else self.rng.randint(4, 900)
        self.lines.append(f"{self._stamp(ms)} {self.host} {source}: {text}")
        n = len(self.lines)
        if ev:
            self.evidence.append(n)
        return n

    # convenience wrappers -------------------------------------------------
    def wpa(self, text: str, *, ev: bool = False, gap: int | None = None) -> int:
        return self.emit(f"wpa_supplicant[{self.wpa_pid}]", f"{self.iface}: {text}", ev=ev, gap=gap)

    def kern(self, text: str, *, ev: bool = False, gap: int | None = None) -> int:
        return self.emit("kernel", f"{self.iface}: {text}", ev=ev, gap=gap)

    def nm(self, text: str, *, level: str = "info", ev: bool = False) -> int:
        ts = self.t.timestamp()
        pad = "  " if level == "info" else "  "
        return self.emit(
            f"NetworkManager[{self.nm_pid}]", f"<{level}>{pad}[{ts:.4f}] {text}", ev=ev
        )

    def dhcp(self, text: str, *, ev: bool = False) -> int:
        return self.emit(f"dhclient[{self.dh_pid}]", text, ev=ev)

    def state(self, frm: str, to: str, *, ev: bool = False) -> int:
        return self.wpa(f"State: {frm} -> {to}", ev=ev)


# --------------------------------------------------------------------------
# noise
# --------------------------------------------------------------------------

UNRELATED_NOISE: list[Callable[[Emitter], None]] = [
    lambda e: e.emit("systemd", "Started Daily apt download activities."),
    lambda e: e.emit("systemd", "Starting Cleanup of Temporary Directories..."),
    lambda e: e.emit(
        "systemd-logind",
        f"New session {e.rng.randint(2, 40)} of user {e.rng.choice(['devuser', 'operator', 'labtech'])}.",
    ),
    lambda e: e.emit("CRON", "(root) CMD (  cd / && run-parts --report /etc/cron.hourly)"),
    lambda e: e.emit("chronyd", f"Selected source 162.159.200.{e.rng.randint(1, 250)}"),
    lambda e: e.emit(
        "avahi-daemon",
        f"Registering new address record for fe80::{e.rng.randint(16, 4095):x} on wlan0.*.",
    ),
    lambda e: e.emit("avahi-daemon", "Withdrawing address record for 169.254.8.2 on wlan0."),
    lambda e: e.emit(
        "bluetoothd", "Endpoint registered: sender=:1.72 path=/MediaEndpoint/A2DPSink"
    ),
    lambda e: e.emit(
        "kernel",
        f"usb {e.rng.randint(1, 3)}-2: new high-speed USB device number {e.rng.randint(3, 20)} using xhci_hcd",
    ),
    lambda e: e.emit(
        "kernel", f"Bluetooth: hci0: unexpected event for opcode 0x{e.rng.randint(0, 65535):04x}"
    ),
    lambda e: e.emit(
        "gnome-shell", "Window manager warning: Buggy client sent a _NET_ACTIVE_WINDOW message"
    ),
    lambda e: e.emit(
        "dbus-daemon", "[system] Successfully activated service 'org.freedesktop.nm_dispatcher'"
    ),
    lambda e: e.emit("kernel", f"thermal thermal_zone0: temperature {e.rng.randint(45, 82)}C"),
    lambda e: e.emit("snapd", "Ensure state already scheduled, skipping."),
    lambda e: e.emit(
        "rtkit-daemon",
        "Successfully made thread 4412 of process 4402 owned by '1000' RT at priority 5.",
    ),
]


def wifi_noise(e: Emitter, bssid: str, ssid: str, freq: int, *, signal: int | None = None) -> None:
    """Benign Wi-Fi chatter: real events that carry no diagnostic signal."""
    sig = signal if signal is not None else e.rng.randint(-62, -38)
    choice = e.rng.randrange(8)
    if choice == 0:
        e.wpa("CTRL-EVENT-SCAN-STARTED ")
    elif choice == 1:
        e.wpa("CTRL-EVENT-SCAN-RESULTS ")
    elif choice == 2:
        e.wpa(f"CTRL-EVENT-BSS-ADDED {e.rng.randint(1, 60)} {_mac(e.rng)}")
    elif choice == 3:
        e.wpa(f"CTRL-EVENT-BSS-REMOVED {e.rng.randint(1, 60)} {_mac(e.rng)}")
    elif choice == 4:
        e.wpa(
            f"CTRL-EVENT-SIGNAL-CHANGE above={1 if sig > -70 else 0} "
            f"signal={sig} noise={e.rng.randint(-96, -88)} txrate={e.rng.choice([6000, 24000, 58500, 130000])}"
        )
    elif choice == 5:
        e.kern(f"Limiting TX power to {e.rng.choice([20, 23, 30])} dBm as advertised by {bssid}")
    elif choice == 6:
        e.wpa(
            f"CTRL-EVENT-REGDOM-CHANGE init={e.rng.choice(['CORE', 'USER', 'COUNTRY_IE'])} type={e.rng.choice(['WORLD', 'COUNTRY'])}"
        )
    else:
        e.nm(
            f"device ({e.iface}): supplicant interface state: {e.rng.choice(['scanning', 'inactive', 'completed'])} -> {e.rng.choice(['scanning', 'inactive', 'authenticating'])}"
        )


def sprinkle(
    e: Emitter, n: int, bssid: str, ssid: str, freq: int, *, signal: int | None = None
) -> None:
    for _ in range(n):
        if e.rng.random() < 0.55:
            e.rng.choice(UNRELATED_NOISE)(e)
        else:
            wifi_noise(e, bssid, ssid, freq, signal=signal)


# --------------------------------------------------------------------------
# shared building blocks
# --------------------------------------------------------------------------


@dataclass
class Ctx:
    e: Emitter
    rng: random.Random
    ssid: str
    bssid: str
    freq: int
    net_id: int
    density: int  # noise lines sprinkled between phases
    signal: int

    def noise(self, lo: int = 0, hi: int | None = None) -> None:
        hi = self.density if hi is None else hi
        sprinkle(
            self.e,
            self.rng.randint(lo, max(lo, hi)),
            self.bssid,
            self.ssid,
            self.freq,
            signal=self.signal,
        )


def scan_phase(c: Ctx, *, found: bool = True) -> None:
    e = c.e
    e.state("INACTIVE", "SCANNING")
    e.wpa("CTRL-EVENT-SCAN-STARTED ")
    c.noise(0, 3)
    e.wpa("CTRL-EVENT-SCAN-RESULTS ")
    if found:
        e.wpa(f"CTRL-EVENT-BSS-ADDED {c.rng.randint(1, 30)} {c.bssid}")
        e.wpa(f"SME: Trying to authenticate with {c.bssid} (SSID='{c.ssid}' freq={c.freq} MHz)")
        e.state("SCANNING", "AUTHENTICATING")


def auth_ok(c: Ctx) -> None:
    e = c.e
    e.kern(f"authenticate with {c.bssid}")
    e.kern(f"send auth to {c.bssid} (try 1/3)")
    e.kern("authenticated")
    e.wpa(f"Trying to associate with {c.bssid} (SSID='{c.ssid}' freq={c.freq} MHz)")
    e.state("AUTHENTICATING", "ASSOCIATING")
    e.kern(f"associate with {c.bssid} (try 1/3)")


def assoc_ok(c: Ctx) -> None:
    e = c.e
    e.kern(f"RX AssocResp from {c.bssid} (capab=0x1431 status=0 aid={c.rng.randint(1, 12)})")
    e.wpa(f"Associated with {c.bssid}")
    e.state("ASSOCIATING", "ASSOCIATED")
    e.kern("associated")


def handshake_ok(c: Ctx) -> None:
    e = c.e
    e.state("ASSOCIATED", "4WAY_HANDSHAKE")
    e.wpa(f"WPA: Key negotiation completed with {c.bssid} [PTK=CCMP GTK=CCMP]")
    e.state("4WAY_HANDSHAKE", "GROUP_HANDSHAKE")
    e.state("GROUP_HANDSHAKE", "COMPLETED")
    e.wpa(f"CTRL-EVENT-CONNECTED - Connection to {c.bssid} completed [id={c.net_id} id_str=]")


def dhcp_ok(c: Ctx) -> tuple[str, str]:
    e = c.e
    ip, gw = _ipv4(c.rng)
    e.nm(f"dhcp4 ({e.iface}): activation: beginning transaction (timeout in 45 seconds)")
    e.dhcp(
        f"DHCPDISCOVER on {e.iface} to 255.255.255.255 port 67 interval {c.rng.choice([3, 5, 7])}"
    )
    e.dhcp(f"DHCPOFFER of {ip} from {gw}")
    e.dhcp(f"DHCPREQUEST for {ip} on {e.iface} to 255.255.255.255 port 67")
    e.dhcp(f"DHCPACK of {ip} from {gw}")
    e.dhcp(f"bound to {ip} -- renewal in {c.rng.randint(1200, 3400)} seconds.")
    e.nm(
        f"device ({e.iface}): state change: ip-config -> ip-check (reason 'none', sys-iface-state: 'managed')"
    )
    return ip, gw


def disconnect(c: Ctx, reason: int, *, local: bool, ev: bool = True) -> None:
    suffix = " locally_generated=1" if local else ""
    c.e.wpa(f"CTRL-EVENT-DISCONNECTED bssid={c.bssid} reason={reason}{suffix}", ev=ev)


# --------------------------------------------------------------------------
# scenarios -- one per root_cause label
# --------------------------------------------------------------------------


def sc_wrong_password(c: Ctx) -> None:
    """Repeated 4-way failures at good signal, with the network temp-disabled.

    Three sub-variants, all seen in the wild:
      * both the explicit PSK message and ``reason=WRONG_KEY`` (easy),
      * only ``reason=WRONG_KEY`` (the PSK line scrolled past / log level),
      * neither -- just N failed handshakes with a rising ``auth_failures``
        counter at strong RSSI, which is what actually distinguishes a bad
        passphrase from a flaky link.
    """
    e = c.e
    sub = c.rng.choices(["explicit", "wrong_key_only", "counter_only"], weights=[5, 3, 2])[0]
    c.signal = c.rng.randint(-58, -35)  # strong link: not a range problem
    attempts = c.rng.randint(3, 4)
    for i in range(1, attempts + 1):
        scan_phase(c)
        auth_ok(c)
        assoc_ok(c)
        e.state("ASSOCIATED", "4WAY_HANDSHAKE")
        e.wpa(f"CTRL-EVENT-SIGNAL-CHANGE above=1 signal={c.signal} noise=-92 txrate=130000")
        psk_ev = sub == "explicit" or sub == "counter_only"
        e.wpa("WPA: 4-Way Handshake failed - pre-shared key may be incorrect", ev=psk_ev)
        disconnect(c, 15, local=True, ev=False)
        if sub != "counter_only":
            e.wpa(
                f'CTRL-EVENT-SSID-TEMP-DISABLED id={c.net_id} ssid="{c.ssid}" auth_failures={i} '
                f"duration={10 * i} reason=WRONG_KEY",
                ev=True,
            )
        else:
            e.wpa(
                f'CTRL-EVENT-SSID-TEMP-DISABLED id={c.net_id} ssid="{c.ssid}" auth_failures={i} '
                f"duration={10 * i} reason=CONN_FAILED",
                ev=True,
            )
        e.state("4WAY_HANDSHAKE", "DISCONNECTED")
        c.noise()
        if i < attempts:
            e.wpa(f'CTRL-EVENT-SSID-REENABLED id={c.net_id} ssid="{c.ssid}"')
    e.nm(
        f"device ({e.iface}): Activation: (wifi) association took too long, failing activation",
        level="warn",
    )


def sc_handshake_timeout(c: Ctx) -> None:
    """EAPOL-Key frames go unanswered on a weak link.

    The trap: wpa_supplicant prints "pre-shared key may be incorrect" for *any*
    4-way handshake failure, including pure timeouts, so that string alone does
    not mean a wrong passphrase. What separates the two is the EAPOL-Key
    timeouts, deauth Reason 15, the weak RSSI, and the absence of a
    ``reason=WRONG_KEY`` temp-disable.
    """
    e = c.e
    c.signal = c.rng.randint(-89, -76)
    scan_phase(c)
    auth_ok(c)
    assoc_ok(c)
    e.state("ASSOCIATED", "4WAY_HANDSHAKE")
    e.wpa(
        f"CTRL-EVENT-SIGNAL-CHANGE above=0 signal={c.signal} noise={c.rng.randint(-94, -89)} txrate=6000",
        ev=True,
    )
    for _ in range(c.rng.randint(2, 4)):
        e.wpa("WPA: EAPOL-Key timeout", ev=True)
        c.noise(0, 2)
    if c.rng.random() < 0.6:
        # Same message as the wrong-password case; deliberately NOT evidence.
        e.wpa("WPA: 4-Way Handshake failed - pre-shared key may be incorrect")
    e.kern(f"deauthenticated from {c.bssid} (Reason: 15=4WAY_HANDSHAKE_TIMEOUT)", ev=True)
    disconnect(c, 15, local=False)
    e.state("4WAY_HANDSHAKE", "DISCONNECTED")


def sc_auth_timeout(c: Ctx) -> None:
    """The AP never answers the 802.11 authentication frames."""
    e = c.e
    scan_phase(c)
    e.kern(f"authenticate with {c.bssid}")
    for t in (1, 2, 3):
        e.kern(f"send auth to {c.bssid} (try {t}/3)", ev=(t == 3))
        c.noise(0, 2)
    e.kern(f"authentication with {c.bssid} timed out", ev=True)
    e.wpa(f"Authentication with {c.bssid} timed out.", ev=True)
    e.wpa(
        f'CTRL-EVENT-SSID-TEMP-DISABLED id={c.net_id} ssid="{c.ssid}" auth_failures=1 duration=10 reason=CONN_FAILED'
    )
    e.state("AUTHENTICATING", "DISCONNECTED")


def sc_assoc_rejected(c: Ctx) -> None:
    """The AP answers the association request with a non-zero status code."""
    e = c.e
    status = c.rng.choice([1, 12, 17, 27, 30])
    scan_phase(c)
    auth_ok(c)
    e.kern(f"RX AssocResp from {c.bssid} (capab=0x1431 status={status} aid=0)", ev=True)
    e.wpa(f"CTRL-EVENT-ASSOC-REJECT bssid={c.bssid} status_code={status}", ev=True)
    e.state("ASSOCIATING", "DISCONNECTED")
    c.noise()
    e.wpa("CTRL-EVENT-SCAN-STARTED ")
    e.wpa(f"CTRL-EVENT-ASSOC-REJECT bssid={c.bssid} status_code={status}", ev=True)


def sc_ap_deauth(c: Ctx) -> None:
    """A healthy session is torn down by the AP with an explicit reason code."""
    e = c.e
    reason = c.rng.choice([1, 2, 3, 4, 5, 8])
    names = {
        1: "UNSPECIFIED",
        2: "PREV_AUTH_NO_LONGER_VALID",
        3: "DEAUTH_LEAVING",
        4: "DISASSOC_DUE_TO_INACTIVITY",
        5: "DISASSOC_AP_BUSY",
        8: "DISASSOC_STA_HAS_LEFT",
    }
    scan_phase(c)
    auth_ok(c)
    assoc_ok(c)
    handshake_ok(c)
    dhcp_ok(c)
    c.noise(3, c.density + 4)
    if c.rng.random() < 0.35:
        # A dip in signal that recovers -- looks like a coverage problem but is not.
        e.wpa(
            f"CTRL-EVENT-SIGNAL-CHANGE above=0 signal={c.rng.randint(-79, -72)} noise=-91 txrate=12000"
        )
        e.wpa(
            f"CTRL-EVENT-SIGNAL-CHANGE above=1 signal={c.rng.randint(-62, -50)} noise=-91 txrate=58500"
        )
    if c.rng.random() < 0.3:
        # Only the supplicant control event survives at this log level.
        disconnect(c, reason, local=False)
    else:
        e.kern(f"deauthenticated from {c.bssid} (Reason: {reason}={names[reason]})", ev=True)
        disconnect(c, reason, local=False)
    e.state("COMPLETED", "DISCONNECTED")
    e.nm(f"device ({e.iface}): supplicant interface state: completed -> disconnected")


def sc_eap_failure(c: Ctx) -> None:
    """802.1X/EAP rejects the supplicant's credentials (enterprise network)."""
    e = c.e
    ident = c.rng.choice(EAP_IDENTITIES)
    method, mname = c.rng.choice([(25, "PEAP"), (21, "TTLS"), (13, "TLS")])
    scan_phase(c)
    auth_ok(c)
    assoc_ok(c)
    e.wpa("CTRL-EVENT-EAP-STARTED EAP authentication started")
    e.wpa(f"CTRL-EVENT-EAP-PROPOSED-METHOD vendor=0 method={method}")
    e.wpa(f"CTRL-EVENT-EAP-METHOD EAP vendor 0 method {method} ({mname}) selected")
    e.wpa(f"EAP: Identity response: {ident}")
    if method == 13:
        e.wpa("CTRL-EVENT-EAP-STATUS status='remote certificate verification' parameter=''")
        e.wpa(
            f"CTRL-EVENT-EAP-PEER-CERT depth=0 subject='/CN=radius.{c.ssid.lower()}.example' hash=sha256"
        )
    c.noise(0, 2)
    e.wpa("CTRL-EVENT-EAP-FAILURE EAP authentication failed", ev=True)
    e.kern(f"deauthenticated from {c.bssid} (Reason: 23=IEEE8021X_FAILED)", ev=True)
    disconnect(c, 23, local=False, ev=False)
    e.wpa(
        f'CTRL-EVENT-SSID-TEMP-DISABLED id={c.net_id} ssid="{c.ssid}" auth_failures=1 duration=10 reason=AUTH_FAILED',
        ev=True,
    )


def sc_dhcp_timeout(c: Ctx) -> None:
    """Layer 2 is fully up; the DHCP server never answers."""
    e = c.e
    scan_phase(c)
    auth_ok(c)
    assoc_ok(c)
    handshake_ok(c)
    e.nm(
        f"device ({e.iface}): state change: config -> ip-config (reason 'none', sys-iface-state: 'managed')"
    )
    e.nm(f"dhcp4 ({e.iface}): activation: beginning transaction (timeout in 45 seconds)")
    for iv in (3, 7, 13, 21):
        e.dhcp(f"DHCPDISCOVER on {e.iface} to 255.255.255.255 port 67 interval {iv}", ev=True)
        c.noise(0, 2)
    e.dhcp("No DHCPOFFERS received.", ev=True)
    e.nm(f"dhcp4 ({e.iface}): state changed no lease", level="warn", ev=True)
    e.nm(
        f"device ({e.iface}): state change: ip-config -> failed (reason 'ip-config-unavailable', sys-iface-state: 'managed')",
        level="warn",
    )


def sc_beacon_loss(c: Ctx) -> None:
    """Connected, then the AP fades out of range."""
    e = c.e
    scan_phase(c)
    auth_ok(c)
    assoc_ok(c)
    handshake_ok(c)
    dhcp_ok(c)
    c.noise(2, c.density + 3)
    for sig in range(-68, -92, -c.rng.choice([5, 6, 7])):
        c.signal = sig
        e.wpa(
            f"CTRL-EVENT-SIGNAL-CHANGE above=0 signal={sig} noise={c.rng.randint(-95, -90)} txrate={c.rng.choice([6000, 12000])}",
            ev=(sig <= -80),
        )
        c.noise(0, 2)
    e.wpa("CTRL-EVENT-BEACON-LOSS ", ev=True)
    e.kern(f"Connection to AP {c.bssid} lost", ev=True)
    disconnect(c, 4, local=False, ev=False)
    e.state("COMPLETED", "DISCONNECTED")


def sc_roaming_failure(c: Ctx) -> None:
    """Associated to one BSS, tries to roam to a better one, and fails to land."""
    e = c.e
    old_bssid = c.bssid
    new_bssid = _mac(c.rng)
    new_freq = c.rng.choice(FREQS_5 if c.freq < 3000 else FREQS_24)
    scan_phase(c)
    auth_ok(c)
    assoc_ok(c)
    handshake_ok(c)
    dhcp_ok(c)
    c.noise(2, c.density + 2)
    e.wpa(
        f"CTRL-EVENT-SIGNAL-CHANGE above=0 signal={c.rng.randint(-78, -72)} noise=-92 txrate=12000"
    )
    e.wpa("CTRL-EVENT-SCAN-STARTED ")
    e.wpa("CTRL-EVENT-SCAN-RESULTS ")
    e.wpa(f"CTRL-EVENT-BSS-ADDED {c.rng.randint(1, 30)} {new_bssid}")
    old_level, new_level = c.rng.randint(-79, -72), c.rng.randint(-58, -48)
    e.wpa(
        f"Considering within-ESS reassociation: current bssid={old_bssid} freq={c.freq} "
        f"level={old_level} selected bssid={new_bssid} freq={new_freq} level={new_level}",
        ev=True,
    )
    e.wpa(
        f"SME: Trying to authenticate with {new_bssid} (SSID='{c.ssid}' freq={new_freq} MHz)",
        ev=True,
    )
    e.kern(f"authenticate with {new_bssid}")
    e.wpa(
        f"CTRL-EVENT-ASSOC-REJECT bssid={new_bssid} status_code={c.rng.choice([17, 30])}", ev=True
    )
    e.wpa(f"CTRL-EVENT-DISCONNECTED bssid={old_bssid} reason=3 locally_generated=1", ev=True)
    e.state("ASSOCIATING", "DISCONNECTED")
    c.bssid = new_bssid


def sc_network_not_found(c: Ctx) -> None:
    """The configured SSID is simply not in any scan result."""
    e = c.e
    for _ in range(c.rng.randint(3, 5)):
        e.state("INACTIVE", "SCANNING")
        e.wpa("CTRL-EVENT-SCAN-STARTED ")
        for _ in range(c.rng.randint(1, 4)):
            e.wpa(f"CTRL-EVENT-BSS-ADDED {c.rng.randint(1, 60)} {_mac(c.rng)}")
        e.wpa("CTRL-EVENT-SCAN-RESULTS ")
        e.wpa("CTRL-EVENT-NETWORK-NOT-FOUND ", ev=True)
        e.state("SCANNING", "INACTIVE")
        c.noise(0, max(1, c.density // 2))


def sc_healthy(c: Ctx) -> None:
    """A clean, successful connection. Nothing to diagnose."""
    c.noise(1, c.density)
    scan_phase(c)
    auth_ok(c)
    assoc_ok(c)
    handshake_ok(c)
    dhcp_ok(c)
    c.noise(2, c.density + 4)
    c.e.wpa("CTRL-EVENT-SUBNET-STATUS-UPDATE status=0")


SCENARIOS: dict[str, Callable[[Ctx], None]] = {
    "WRONG_PASSWORD": sc_wrong_password,
    "HANDSHAKE_TIMEOUT": sc_handshake_timeout,
    "AUTH_TIMEOUT": sc_auth_timeout,
    "ASSOC_REJECTED": sc_assoc_rejected,
    "AP_DEAUTH": sc_ap_deauth,
    "EAP_FAILURE": sc_eap_failure,
    "DHCP_TIMEOUT": sc_dhcp_timeout,
    "BEACON_LOSS_WEAK_SIGNAL": sc_beacon_loss,
    "ROAMING_FAILURE": sc_roaming_failure,
    "NETWORK_NOT_FOUND": sc_network_not_found,
    "HEALTHY": sc_healthy,
}


# --------------------------------------------------------------------------
# hard variants
# --------------------------------------------------------------------------


def apply_misleading(c: Ctx, label: str) -> None:
    """Inject a real-looking but irrelevant error before the true failure.

    These are events that genuinely occur in healthy logs (a prior session
    ending, a transient scan failure) and that a naive keyword matcher will
    happily latch onto. They are deliberately *not* marked as evidence.
    """
    e = c.e
    decoys = [
        lambda: e.wpa(f"CTRL-EVENT-DISCONNECTED bssid={_mac(c.rng)} reason=3 locally_generated=1"),
        lambda: e.kern(
            f"deauthenticating from {_mac(c.rng)} by local choice (Reason: 3=DEAUTH_LEAVING)"
        ),
        lambda: e.wpa("CTRL-EVENT-SCAN-FAILED ret=-16 retry=1"),
        lambda: e.wpa("CTRL-EVENT-BEACON-LOSS "),
        lambda: e.dhcp(f"DHCPDISCOVER on {e.iface} to 255.255.255.255 port 67 interval 5"),
        lambda: e.emit("kernel", "wlan0: cfg80211: Regulatory domain changed to country: US"),
        lambda: e.wpa(f"CTRL-EVENT-ASSOC-REJECT bssid={_mac(c.rng)} status_code=30"),
        lambda: e.wpa("CTRL-EVENT-NETWORK-NOT-FOUND "),
    ]
    # Never plant the decoy that *is* the true signal for this label.
    banned = {
        "AP_DEAUTH": {0, 1},
        "BEACON_LOSS_WEAK_SIGNAL": {3},
        "DHCP_TIMEOUT": {4},
        "ROAMING_FAILURE": {0, 1, 6},
        "ASSOC_REJECTED": {6},
        "NETWORK_NOT_FOUND": {7},
    }.get(label, set())
    pool = [d for i, d in enumerate(decoys) if i not in banned]
    for fn in c.rng.sample(pool, k=min(len(pool), c.rng.randint(1, 3))):
        fn()


def apply_recovery(c: Ctx) -> None:
    """A transient failure that resolves, *before* the real failure appears.

    The correct answer is still the label's failure; a model that reports the
    first error it sees gets this wrong.
    """
    e = c.e
    e.wpa("CTRL-EVENT-SCAN-STARTED ")
    e.wpa(f"CTRL-EVENT-ASSOC-REJECT bssid={_mac(c.rng)} status_code=30")
    e.wpa("CTRL-EVENT-SCAN-RESULTS ")
    e.wpa(f"SME: Trying to authenticate with {c.bssid} (SSID='{c.ssid}' freq={c.freq} MHz)")
    e.wpa(f"Associated with {c.bssid}")
    e.wpa(f"WPA: Key negotiation completed with {c.bssid} [PTK=CCMP GTK=CCMP]")
    e.wpa(f"CTRL-EVENT-CONNECTED - Connection to {c.bssid} completed [id={c.net_id} id_str=]")
    e.state("4WAY_HANDSHAKE", "COMPLETED")
    e.wpa(f"CTRL-EVENT-DISCONNECTED bssid={c.bssid} reason=3 locally_generated=1")
    e.state("COMPLETED", "DISCONNECTED")


# --------------------------------------------------------------------------
# case assembly
# --------------------------------------------------------------------------


def build_case(case_id: str, split: str, label: str, variant: str, seed: int) -> dict:
    rng = random.Random(seed)
    host = rng.choice(HOSTS)
    ssid = rng.choice(SSIDS)
    freq = rng.choice(FREQS_24 + FREQS_5)
    start = datetime(
        2025,
        rng.randint(1, 12),
        rng.randint(1, 28),
        rng.randint(0, 23),
        rng.randint(0, 59),
        rng.randint(0, 59),
    )
    e = Emitter(
        rng=rng,
        host=host,
        t=start,
        wpa_pid=rng.randint(700, 9000),
        nm_pid=rng.randint(700, 9000),
        dh_pid=rng.randint(700, 9000),
    )
    density = {"heavy_noise": rng.randint(9, 18)}.get(variant, rng.randint(1, 5))
    c = Ctx(
        e=e,
        rng=rng,
        ssid=ssid,
        bssid=_mac(rng),
        freq=freq,
        net_id=rng.randint(0, 3),
        density=density,
        signal=rng.randint(-62, -38),
    )

    # Preamble: daemon start-up, always present, never evidence.
    e.emit(f"wpa_supplicant[{e.wpa_pid}]", "Successfully initialized wpa_supplicant")
    e.wpa("CTRL-EVENT-REGDOM-CHANGE init=CORE type=WORLD")
    c.noise(1, max(2, density))

    if variant == "misleading":
        apply_misleading(c, label)
        c.noise(0, 2)
    if variant == "transient_recovery" and label != "HEALTHY":
        apply_recovery(c)
        c.noise(1, 3)

    SCENARIOS[label](c)
    c.noise(1, max(2, density))

    # Pad to a realistic length.
    target = rng.randint(40, 400)
    guard = 0
    while len(e.lines) < target and guard < 600:
        sprinkle(e, 1, c.bssid, c.ssid, c.freq, signal=c.signal)
        guard += 1

    if variant == "truncated":
        # Log rotation cut the tail off. Keep at least the evidence we promised.
        keep = max(max(e.evidence, default=1) + rng.randint(0, 3), 40)
        e.lines = e.lines[:keep]
        e.evidence = [n for n in e.evidence if n <= len(e.lines)]

    return {
        "id": case_id,
        "split": split,
        "root_cause": label,
        "variant": variant,
        "seed": seed,
        "n_lines": len(e.lines),
        "evidence_lines": sorted(set(e.evidence)),
        "entities": {"ssid": ssid, "bssid": c.bssid, "host": host, "freq": freq},
        "log": "\n".join(e.lines),
    }


def generate_split(split: str, n: int, base_seed: int) -> list[dict]:
    labels = list(SCENARIOS)
    cases: list[dict] = []
    picker = random.Random(base_seed)
    for i in range(n):
        label = labels[i % len(labels)]
        # First pass over the label set is always plain, so every class has an
        # easy example; after that, variants are sampled.
        variant = (
            "plain" if i < len(labels) else picker.choices(VARIANTS, weights=[1, 2, 3, 2, 3])[0]
        )
        seed = base_seed + i * 977
        cases.append(build_case(f"{split}_{i:04d}", split, label, variant, seed))
    return cases


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=Path("data/synthetic"))
    ap.add_argument("--dev-n", type=int, default=44)
    ap.add_argument("--test-n", type=int, default=66)
    ap.add_argument("--dev-seed", type=int, default=20250925)
    ap.add_argument("--test-seed", type=int, default=77001313)
    args = ap.parse_args()

    for split, n, seed in (
        ("dev", args.dev_n, args.dev_seed),
        ("test", args.test_n, args.test_seed),
    ):
        cases = generate_split(split, n, seed)
        d = args.out / split
        d.mkdir(parents=True, exist_ok=True)
        path = d / "cases.jsonl"
        with path.open("w") as fh:
            for case in cases:
                fh.write(json.dumps(case) + "\n")
        lens = [c["n_lines"] for c in cases]
        print(
            f"{split}: {len(cases)} cases -> {path}  "
            f"(lines {min(lens)}-{max(lens)}, mean {sum(lens) / len(lens):.0f})"
        )


if __name__ == "__main__":
    main()
