# Where the lines come from

A single Wi-Fi failure produces lines from several daemons, each with a
different view. Knowing which component spoke tells you which layer failed.

| Prefix | Component | View |
|---|---|---|
| `wpa_supplicant[pid]: wlan0:` | the supplicant | the authoritative view of scan/auth/assoc/key state |
| `kernel: wlan0:` | mac80211 / cfg80211 | what the radio and driver actually did, including frame-level retries |
| `NetworkManager[pid]:` | connection manager | policy, activation attempts, DHCP orchestration |
| `dhclient[pid]:` / `dhcpcd[pid]:` | DHCP client | layer 3 address acquisition |
| `avahi-daemon`, `systemd`, `CRON`, `bluetoothd` | unrelated | noise; never evidence for a Wi-Fi diagnosis |

## Corroboration

The supplicant and the kernel narrate the same events from different sides:

```
kernel:          wlan0: send auth to <MAC_1> (try 1/3)
kernel:          wlan0: authenticated
wpa_supplicant:  wlan0: Trying to associate with <MAC_1> (SSID='<SSID_1>' freq=5180 MHz)
kernel:          wlan0: RX AssocResp from <MAC_1> (capab=0x1431 status=0 aid=3)
wpa_supplicant:  wlan0: Associated with <MAC_1>
```

Two independent sources agreeing is much stronger evidence than one line. The
kernel's `(try N/3)` counters in particular reveal whether frames were sent and
ignored (a timeout) or answered with a refusal (a status code).

Clock note: syslog timestamps have one-second resolution, so several events can
share a timestamp. Use line order, not timestamps, to establish sequence.
