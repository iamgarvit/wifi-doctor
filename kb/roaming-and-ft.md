# Roaming and 802.11r fast transition

Roaming is the client deciding to move from one BSS to another **within the
same ESS** (same SSID, different AP). The client owns this decision; the AP can
suggest but not force it.

A roam attempt in the log:

```
wlan0: Considering within-ESS reassociation: current bssid=<MAC_1> freq=2422 level=-74
       selected bssid=<MAC_2> freq=5220 level=-58
wlan0: SME: Trying to authenticate with <MAC_2> (SSID='<SSID_1>' freq=5220 MHz)
wlan0: CTRL-EVENT-CONNECTED - Connection to <MAC_2> completed
```

The key tell is **two different BSSIDs for one SSID** inside one session.

## Fast transition (802.11r)

Full reauthentication on every roam costs hundreds of milliseconds — enough to
break a voice call. 802.11r pre-distributes key material so the client can
reassociate without redoing the full 4-way handshake:

- **Over-the-air FT** — the client talks to the target AP directly.
- **Over-the-DS FT** — the client talks to the target through the current AP.

Related standards: **802.11k** gives the client a neighbour report so it knows
which APs to consider, and **802.11v** lets the network suggest a transition
(BSS Transition Management).

## Roaming failure

The client decides to leave a working AP, fails to land on the new one, and
ends up with nothing:

```
wlan0: Considering within-ESS reassociation: ... selected bssid=<MAC_2> ...
wlan0: CTRL-EVENT-ASSOC-REJECT bssid=<MAC_2> status_code=17
wlan0: CTRL-EVENT-DISCONNECTED bssid=<MAC_1> reason=3 locally_generated=1
```

Note `locally_generated=1` against the **old** BSSID: the client tore down the
old association itself. That is the difference between a roaming failure and
the AP kicking the client off.

Common causes: inconsistent 802.11r/PMF/mobility-domain configuration across
APs, the target AP at its client limit, or an over-eager roam threshold making
the client chase APs it cannot actually reach.
