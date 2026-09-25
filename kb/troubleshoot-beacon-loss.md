# Troubleshooting: BEACON_LOSS_WEAK_SIGNAL

**Class:** `BEACON_LOSS_WEAK_SIGNAL` — the client drifted out of usable range
of the serving AP and stopped hearing its beacons.

## Signature

```
wlan0: CTRL-EVENT-CONNECTED - Connection to <MAC_1> completed [id=0 id_str=]
wlan0: CTRL-EVENT-SIGNAL-CHANGE above=0 signal=-68 noise=-92 txrate=12000
wlan0: CTRL-EVENT-SIGNAL-CHANGE above=0 signal=-75 noise=-92 txrate=6000
wlan0: CTRL-EVENT-SIGNAL-CHANGE above=0 signal=-83 noise=-92 txrate=6000
wlan0: CTRL-EVENT-BEACON-LOSS
kernel: wlan0: Connection to AP <MAC_1> lost
```

The decisive combination is:

- the session reached `COMPLETED` — this is a drop, not a connect failure;
- a **monotonically declining run** of `signal=` values ending below about
  −80 dBm, with `txrate` collapsing;
- `CTRL-EVENT-BEACON-LOSS` and/or `Connection to AP ... lost`.

A single dip that recovers is not beacon loss — look for the trend. If the AP
sent an explicit deauth with a reason code at adequate signal, it is
`AP_DEAUTH` instead. See `rssi-thresholds.md` for what the numbers mean.

## Fixes

1. Improve coverage where the client actually is: add an AP or relocate the
   existing one. Extenders halve throughput but do restore coverage.
2. Check for a new physical obstruction, or the client having moved.
3. Check whether the client should have roamed instead — if another AP in the
   ESS was reachable, the roam threshold is set too conservatively. See
   `roaming-and-ft.md`.
4. Prefer 2.4 GHz at the cell edge; 5 GHz attenuates faster through walls.
5. Check the AP's beacon interval and DTIM settings against the client's
   power-save configuration.
