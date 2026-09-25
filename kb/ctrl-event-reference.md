# wpa_supplicant CTRL-EVENT reference

wpa_supplicant emits machine-readable events on its control interface; they are
what a diagnosis should anchor to, because they are stable across versions
while free-text debug lines are not.

| Event | Meaning |
|---|---|
| `CTRL-EVENT-SCAN-STARTED` / `-RESULTS` | a scan began / results are ready |
| `CTRL-EVENT-SCAN-FAILED ret=-N` | the driver refused the scan (often transient) |
| `CTRL-EVENT-BSS-ADDED` / `-REMOVED` | a BSS entered or left the scan cache |
| `CTRL-EVENT-NETWORK-NOT-FOUND` | none of the configured networks were seen |
| `CTRL-EVENT-AUTH-REJECT ... status_code=N` | the AP refused 802.11 authentication |
| `CTRL-EVENT-ASSOC-REJECT bssid=.. status_code=N` | the AP refused association |
| `CTRL-EVENT-CONNECTED - Connection to .. completed` | fully connected at layer 2 |
| `CTRL-EVENT-DISCONNECTED bssid=.. reason=N [locally_generated=1]` | link went down |
| `CTRL-EVENT-SSID-TEMP-DISABLED id=N ssid=".." auth_failures=N duration=N reason=X` | the network was blacklisted for `duration` seconds |
| `CTRL-EVENT-SSID-REENABLED` | the blacklist expired |
| `CTRL-EVENT-EAP-STARTED` / `-METHOD` / `-SUCCESS` / `-FAILURE` | 802.1X progress |
| `CTRL-EVENT-EAP-PEER-CERT` | a certificate in the server's chain |
| `CTRL-EVENT-BEACON-LOSS` | beacons from the serving AP stopped arriving |
| `CTRL-EVENT-SIGNAL-CHANGE above=N signal=-NN noise=-NN txrate=N` | signal crossed a threshold |
| `CTRL-EVENT-REGDOM-CHANGE` | regulatory domain changed (usually benign) |
| `CTRL-EVENT-SUBNET-STATUS-UPDATE status=N` | the subnet looks the same/different after a roam |

## The one to read carefully

`CTRL-EVENT-SSID-TEMP-DISABLED` carries a `reason=` field that is wpa_supplicant's
*own verdict*, not an 802.11 code:

- `reason=WRONG_KEY` — the supplicant concluded the PSK is wrong.
- `reason=AUTH_FAILED` — 802.1X/EAP rejected the client.
- `reason=CONN_FAILED` — the attempt failed for some other reason.

`auth_failures=N` counts consecutive failures for that network and drives the
backoff in `duration=`. A rising counter is strong evidence of a *persistent*
configuration problem rather than a one-off radio event.
