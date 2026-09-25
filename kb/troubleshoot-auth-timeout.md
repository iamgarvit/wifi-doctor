# Troubleshooting: AUTH_TIMEOUT

**Class:** `AUTH_TIMEOUT` — the AP never answered the 802.11 Authentication
frames. The client never reached association.

## Signature

```
wlan0: SME: Trying to authenticate with <MAC_1> (SSID='<SSID_1>' freq=2437 MHz)
kernel: wlan0: send auth to <MAC_1> (try 1/3)
kernel: wlan0: send auth to <MAC_1> (try 2/3)
kernel: wlan0: send auth to <MAC_1> (try 3/3)
kernel: wlan0: authentication with <MAC_1> timed out
wlan0: Authentication with <MAC_1> timed out.
```

The decisive combination is the exhausted `(try N/3)` retry sequence followed
by a timeout, with the furthest state reached being `AUTHENTICATING`. There is
no status code, because no response frame ever arrived — that absence is what
separates this from `ASSOC_REJECTED`, where the AP *did* answer.

## Fixes

1. Confirm the AP is actually up and serving that BSSID; the scan cache can be
   stale, so force a fresh scan.
2. Check whether the client is at the very edge of range — auth frames are sent
   at low rates but still need a usable uplink.
3. Check the AP for a MAC access-control list silently dropping this client.
4. Check for AP overload; some APs stop answering rather than sending status
   17.
5. Try a different BSS in the same ESS, or the other band, to isolate one AP.
