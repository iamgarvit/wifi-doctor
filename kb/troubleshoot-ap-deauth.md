# Troubleshooting: AP_DEAUTH

**Class:** `AP_DEAUTH` — a working, fully connected session was ended by the
AP sending a deauthentication or disassociation frame.

## Signature

```
wlan0: CTRL-EVENT-CONNECTED - Connection to <MAC_1> completed [id=0 id_str=]
... normal traffic ...
kernel: wlan0: deauthenticated from <MAC_1> (Reason: 4=DISASSOC_DUE_TO_INACTIVITY)
wlan0: CTRL-EVENT-DISCONNECTED bssid=<MAC_1> reason=4
wlan0: State: COMPLETED -> DISCONNECTED
```

The decisive combination is:

- the session reached `COMPLETED` first — this is not a connection failure;
- a deauth/disassoc carrying a **reason code**;
- **no** `locally_generated=1` on the `CTRL-EVENT-DISCONNECTED` line. If that
  flag is present, the client left; the AP did not eject it.
- signal was adequate. A drop preceded by a declining signal trend and
  `CTRL-EVENT-BEACON-LOSS` is `BEACON_LOSS_WEAK_SIGNAL` instead.

At a lower log level only the supplicant's `CTRL-EVENT-DISCONNECTED bssid=..
reason=N` survives, with no kernel line. That is still sufficient.

## Fixes by reason code

- **4 (inactivity)** — the AP's idle timeout is shorter than the client's
  power-save behaviour. Raise the AP idle timeout, or disable aggressive client
  power save.
- **5 (AP unable to handle all associated STAs)** — the AP is oversubscribed.
- **3 / 8 (STA is leaving)** from the AP usually means an admin action, an AP
  reboot, or a firmware-initiated cleanup.
- **1 (unspecified)** — check the AP logs; common with band steering, client
  steering, and captive-portal session expiry.
- **2 (previous authentication no longer valid)** — the AP lost the client's
  state, often after an AP restart.
- **34 (excessive missing ACKs)** — the AP is not hearing the client's
  acknowledgements; treat as a link-quality problem despite the reason code.
