# The wpa_supplicant state machine

wpa_supplicant logs every state change as:

```
wlan0: State: ASSOCIATED -> 4WAY_HANDSHAKE
```

The happy path for a WPA2/WPA3-Personal network is:

```
DISCONNECTED/INACTIVE -> SCANNING -> AUTHENTICATING -> ASSOCIATING
   -> ASSOCIATED -> 4WAY_HANDSHAKE -> GROUP_HANDSHAKE -> COMPLETED
```

On an 802.1X network, `ASSOCIATED` is followed by EAP exchange and then the
4-way handshake once the EAP method has produced key material.

| State | What is happening | Typical failure here |
|---|---|---|
| `SCANNING` | Probing channels for the configured SSID | `CTRL-EVENT-NETWORK-NOT-FOUND` |
| `AUTHENTICATING` | 802.11 Authentication frames (Open System or SAE) | authentication timeout, `CTRL-EVENT-AUTH-REJECT` |
| `ASSOCIATING` | (Re)Association Request sent | `CTRL-EVENT-ASSOC-REJECT status_code=N` |
| `ASSOCIATED` | Layer 2 link exists, no keys yet | EAP failure on enterprise networks |
| `4WAY_HANDSHAKE` | EAPOL-Key exchange deriving the PTK | wrong PSK, `WPA: EAPOL-Key timeout`, Reason 15 |
| `GROUP_HANDSHAKE` | Receiving the GTK | Reason 16 |
| `COMPLETED` | Link is up and encrypted | nothing — IP problems are above this layer |

## Why the state matters more than the error text

**The last state the client reached bounds the set of possible root causes.**
A log that never leaves `SCANNING` cannot have a passphrase problem. A log that
reaches `COMPLETED` and then fails has a problem *above* layer 2 — DHCP,
routing, or the AP ending the session — not an association problem.

When diagnosing, get the timeline first, find the furthest state reached, and
only then look for error lines near that point.
