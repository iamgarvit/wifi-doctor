# Troubleshooting: HEALTHY

**Class:** `HEALTHY` — the log shows a successful connection and no unresolved
failure. The correct action is to report that nothing is wrong.

## Signature

```
wlan0: State: ASSOCIATED -> 4WAY_HANDSHAKE
wlan0: WPA: Key negotiation completed with <MAC_1> [PTK=CCMP GTK=CCMP]
wlan0: State: 4WAY_HANDSHAKE -> GROUP_HANDSHAKE
wlan0: State: GROUP_HANDSHAKE -> COMPLETED
wlan0: CTRL-EVENT-CONNECTED - Connection to <MAC_1> completed [id=0 id_str=]
dhclient: DHCPACK of <IPV4_1> from <IPV4_2>
dhclient: bound to <IPV4_1> -- renewal in 1707 seconds.
```

## Recovered transients

A healthy log may still contain errors. These are all normal and must **not**
be reported as a root cause when the log later reaches `COMPLETED` and stays
there:

- a `CTRL-EVENT-NETWORK-NOT-FOUND` before the AP came into range;
- a `CTRL-EVENT-SCAN-FAILED ret=-16` (the driver was busy);
- an `CTRL-EVENT-ASSOC-REJECT status_code=30` followed by a successful retry;
- a `CTRL-EVENT-DISCONNECTED ... locally_generated=1` from a *previous*
  session ending cleanly;
- a brief `signal=` dip that recovers;
- `CTRL-EVENT-REGDOM-CHANGE` and TX-power limit lines, which are routine.

## How to check

Work backwards from the end of the log. Find the last `CTRL-EVENT-CONNECTED`
or `CTRL-EVENT-DISCONNECTED`, whichever is later. If the log ends connected —
and, where DHCP lines are present, with a `DHCPACK` — the answer is `HEALTHY`,
with the success lines cited as evidence.

Reporting a fault that is not there is as wrong as missing one that is. There
is no partial credit for a plausible-sounding false alarm.
