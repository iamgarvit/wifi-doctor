# Disambiguating confusable failures

Most wrong diagnoses come from matching a single keyword. These are the pairs
that actually get confused, and the signal that separates them.

## WRONG_PASSWORD vs HANDSHAKE_TIMEOUT

Both fail in `4WAY_HANDSHAKE`, both end with Reason 15, and wpa_supplicant
prints `WPA: 4-Way Handshake failed - pre-shared key may be incorrect` for
**both**. That message is not a discriminator.

| Signal | WRONG_PASSWORD | HANDSHAKE_TIMEOUT |
|---|---|---|
| `signal=` near the failure | strong, −60 dBm or better | weak, −75 dBm or worse |
| `WPA: EAPOL-Key timeout` | absent | present, usually repeated |
| `CTRL-EVENT-SSID-TEMP-DISABLED reason=` | `WRONG_KEY` | `CONN_FAILED`, or no temp-disable |
| `auth_failures=N` | rises 1, 2, 3 across attempts | usually a single attempt |
| `txrate=` | high | collapsed to 6000 |

A rising `auth_failures` counter at strong signal is a persistent
configuration problem. Repeated EAPOL timeouts at −80 dBm are a radio problem.

## WRONG_PASSWORD vs EAP_FAILURE

Different layers entirely. `CTRL-EVENT-EAP-FAILURE` and Reason 23 mean 802.1X
rejected the client, and the 4-way handshake was never reached. If the log
contains any `CTRL-EVENT-EAP-*` line, it is an enterprise network and a PSK
diagnosis is wrong.

## AP_DEAUTH vs BEACON_LOSS_WEAK_SIGNAL

Both end a working session.

- **AP_DEAUTH** — the AP sent a deauth/disassoc frame with a reason code, at
  otherwise adequate signal. `CTRL-EVENT-DISCONNECTED` has **no**
  `locally_generated=1`.
- **BEACON_LOSS_WEAK_SIGNAL** — `CTRL-EVENT-BEACON-LOSS` and/or
  `Connection to AP ... lost`, preceded by a *declining* run of
  `CTRL-EVENT-SIGNAL-CHANGE` values. The AP did not say anything; it simply
  stopped being audible.

A single dip in signal that recovers is not beacon loss. Look for a trend.

## AP_DEAUTH vs ROAMING_FAILURE

If the client itself decided to move (`Considering within-ESS reassociation`,
a second BSSID for the same SSID) and the disconnect from the old BSS carries
`locally_generated=1`, it is a roaming failure. The AP kicking a stationary
client is `AP_DEAUTH`.

## ASSOC_REJECTED vs ROAMING_FAILURE

Both show `CTRL-EVENT-ASSOC-REJECT`. The question is *which BSS*. A rejection
from the only BSS the client ever tried is `ASSOC_REJECTED`. A rejection from a
**new** BSS after the client was already connected to another one is
`ROAMING_FAILURE`.

## Anything vs DHCP_TIMEOUT

If `CTRL-EVENT-CONNECTED` and `WPA: Key negotiation completed` are present, Wi-Fi
worked. A failure after that point is layer 3. Do not diagnose a Wi-Fi fault.

## Anything vs HEALTHY

Logs contain old errors. A failure that is followed by
`CTRL-EVENT-CONNECTED` and a `DHCPACK`, with no later failure, is a **recovered
transient** — the correct answer is `HEALTHY`. Always check whether the log
ends in a good state before reporting the first error you find.
