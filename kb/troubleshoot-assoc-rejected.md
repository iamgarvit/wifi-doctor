# Troubleshooting: ASSOC_REJECTED

**Class:** `ASSOC_REJECTED` — the AP answered the (Re)Association Request with
a non-zero status code. The AP is refusing, deliberately and explicitly.

## Signature

```
kernel: wlan0: RX AssocResp from <MAC_1> (capab=0x1431 status=17 aid=0)
wlan0: CTRL-EVENT-ASSOC-REJECT bssid=<MAC_1> status_code=17
wlan0: State: ASSOCIATING -> DISCONNECTED
```

The `status_code` is the diagnosis — always look it up in `status-codes.md`
and report what it means, not just the number. `aid=0` in the kernel line
confirms no association ID was assigned.

Check the rejection is from the **only** BSS the client tried. A rejection from
a new BSS after the client was already connected elsewhere is
`ROAMING_FAILURE`, not this.

## Fixes by status code

- **17 (AP unable to handle additional STAs)** — the AP is at its client
  limit. Retry, use another AP, or raise the limit.
- **30 (rejected temporarily; try again later)** — load or transition
  management. Usually self-resolving; back off and retry.
- **12 / 1 / 37 (generic refusal)** — check MAC filtering, an access-control
  list, band steering, or a captive-portal policy on the AP.
- **10 / 18 / 27 (capability mismatch)** — the AP requires rates or HT features
  the client did not advertise. Check for a legacy client on an HT-only SSID,
  or an incorrect BSSBasicRateSet on the AP.
- **53 (invalid PMKID)** — a stale cached PMK. Clear it and force a full
  authentication.
