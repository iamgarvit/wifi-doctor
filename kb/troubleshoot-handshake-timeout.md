# Troubleshooting: HANDSHAKE_TIMEOUT

**Class:** `HANDSHAKE_TIMEOUT` — the 4-way handshake did not complete because
EAPOL-Key frames were lost, not because the credentials were wrong.

## Signature

```
wlan0: State: ASSOCIATED -> 4WAY_HANDSHAKE
wlan0: CTRL-EVENT-SIGNAL-CHANGE above=0 signal=-84 noise=-91 txrate=6000
wlan0: WPA: EAPOL-Key timeout
wlan0: WPA: EAPOL-Key timeout
kernel: wlan0: deauthenticated from <MAC_1> (Reason: 15=4WAY_HANDSHAKE_TIMEOUT)
```

The decisive combination is:

- one or more `WPA: EAPOL-Key timeout` lines;
- **weak signal** (−75 dBm or worse) and often `txrate=6000`;
- deauth Reason 15;
- **no** `reason=WRONG_KEY` temp-disable.

The message `WPA: 4-Way Handshake failed - pre-shared key may be incorrect`
often appears here too and must be ignored as a discriminator.

## Fixes

1. Move closer to the AP, or move the AP; verify the signal improves.
2. Check for interference and co-channel congestion on that channel; try the
   other band.
3. If the client is at the cell edge, add an AP rather than raising TX power —
   raising AP power alone makes the downlink louder but not the uplink.
4. Check for a driver power-save bug: temporarily disable power save
   (`iw dev wlan0 set power_save off`) and retry.
5. If the signal is strong and EAPOL frames still time out, suspect an AP or
   driver fault, or a PMF/802.11w mismatch.
