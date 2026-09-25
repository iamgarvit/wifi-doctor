# Regulatory domain, channels and bands

```
wlan0: CTRL-EVENT-REGDOM-CHANGE init=CORE type=WORLD
kernel: wlan0: cfg80211: Regulatory domain changed to country: US
kernel: wlan0: Limiting TX power to 20 dBm as advertised by <MAC_1>
```

These lines are **usually benign** and should not be cited as a root cause on
their own. They matter in two situations.

**A `WORLD` regulatory domain** is the conservative default a client uses
before it learns the country. In `WORLD` mode many 5 GHz channels are
passive-scan-only or forbidden, so a client can genuinely fail to find an AP
that is transmitting on a channel it is not allowed to use. Symptom:
`CTRL-EVENT-NETWORK-NOT-FOUND` for a network that is demonstrably on the air.

**DFS channels** (many 5 GHz channels, e.g. 52–144 in most domains) require the
AP to perform radar detection and to vacate the channel if it sees radar. When
that happens the AP moves and clients are disconnected, often with a channel
switch announcement first.

Band reference:

| Band | Frequencies | Notes |
|---|---|---|
| 2.4 GHz | 2412–2484 MHz | 3 non-overlapping channels, most range, most interference |
| 5 GHz | 5180–5825 MHz | many channels, some DFS, shorter range |
| 6 GHz | 5955–7115 MHz | Wi-Fi 6E/7 only; WPA3 required |

TX power limits advertised by the AP are informational.
