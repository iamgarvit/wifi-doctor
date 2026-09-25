# Scanning and BSS selection

Before it can connect, wpa_supplicant scans, builds a BSS cache, and picks a
candidate for the configured network.

```
wlan0: State: INACTIVE -> SCANNING
wlan0: CTRL-EVENT-SCAN-STARTED
wlan0: CTRL-EVENT-BSS-ADDED 14 <MAC_1>
wlan0: CTRL-EVENT-SCAN-RESULTS
wlan0: SME: Trying to authenticate with <MAC_1> (SSID='<SSID_1>' freq=5180 MHz)
```

Selection is by signal level, band preference and estimated throughput, among
the BSSs whose security configuration matches the client's network block.

## `CTRL-EVENT-NETWORK-NOT-FOUND`

The scan completed and none of the configured networks were among the results.
The client then sleeps and rescans, so this event repeats — a run of them is
the signature of the network genuinely not being there.

Causes: the SSID is not being broadcast (and the client is not configured with
`scan_ssid=1`), the AP is on a channel the client's regulatory domain forbids
(commonly a 5 GHz DFS or a 6 GHz channel), the AP is off or out of range, or
the SSID is misspelled in the configuration.

**A single** `CTRL-EVENT-NETWORK-NOT-FOUND` **early in a log that later
connects is normal** — the client scanned before the AP was in range. Only a
sustained run with no subsequent association is a diagnosis.

Frequencies map to bands: 2412–2484 MHz is 2.4 GHz, 5180–5825 MHz is 5 GHz,
5955–7115 MHz is 6 GHz.
