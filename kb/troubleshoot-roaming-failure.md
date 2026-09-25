# Troubleshooting: ROAMING_FAILURE

**Class:** `ROAMING_FAILURE` — the client left a working AP to move to a
better one in the same ESS, failed to associate with the target, and ended up
disconnected.

## Signature

```
wlan0: CTRL-EVENT-CONNECTED - Connection to <MAC_1> completed [id=0 id_str=]
wlan0: CTRL-EVENT-SIGNAL-CHANGE above=0 signal=-74 noise=-92 txrate=12000
wlan0: Considering within-ESS reassociation: current bssid=<MAC_1> freq=2422 level=-74
       selected bssid=<MAC_2> freq=5220 level=-58
wlan0: SME: Trying to authenticate with <MAC_2> (SSID='<SSID_1>' freq=5220 MHz)
wlan0: CTRL-EVENT-ASSOC-REJECT bssid=<MAC_2> status_code=17
wlan0: CTRL-EVENT-DISCONNECTED bssid=<MAC_1> reason=3 locally_generated=1
```

The decisive combination is:

- **two different BSSIDs for the same SSID** within one session;
- an explicit reassociation decision, or authentication attempted against a
  BSSID the client was not previously using;
- a failure on the **new** BSS;
- `locally_generated=1` on the disconnect from the **old** BSS — the client
  tore that down itself.

Without the second BSSID it is a plain `ASSOC_REJECTED`. Without the client's
own decision to move it is `AP_DEAUTH`.

## Fixes

1. Make 802.11r configuration consistent across all APs in the ESS: same
   mobility domain, same PMF setting, same AKM list. A partial rollout is a
   classic cause.
2. Check the target AP's client limit (status 17) and load.
3. Enable 802.11k neighbour reports so the client picks reachable targets.
4. Tune the client's roam threshold — roaming too early, at a signal the target
   cannot actually sustain, causes exactly this.
5. As a diagnostic, lock the client to one BSSID and confirm the session is
   stable; that isolates roaming from coverage.
