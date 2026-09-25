# Troubleshooting: NETWORK_NOT_FOUND

**Class:** `NETWORK_NOT_FOUND` — scans completed and the configured SSID was
not among the results. The client never attempted to authenticate.

## Signature

```
wlan0: State: INACTIVE -> SCANNING
wlan0: CTRL-EVENT-SCAN-STARTED
wlan0: CTRL-EVENT-BSS-ADDED 12 <MAC_2>
wlan0: CTRL-EVENT-SCAN-RESULTS
wlan0: CTRL-EVENT-NETWORK-NOT-FOUND
wlan0: State: SCANNING -> INACTIVE
```

The decisive combination is a **repeated** cycle of scan →
`CTRL-EVENT-NETWORK-NOT-FOUND`, with no `SME: Trying to authenticate` line
anywhere. Other BSSs *are* being found, which shows the radio works.

One such event early in a log that later connects is normal and must not be
diagnosed — see `disambiguation-guide.md`.

## Fixes

1. Check the SSID spelling in the configuration, including case and trailing
   whitespace.
2. Confirm the AP is powered on and broadcasting; check from another device.
3. For a hidden SSID, set `scan_ssid=1` in the network block so the client
   sends directed probe requests.
4. Check the regulatory domain. A client in `WORLD` mode cannot use many 5 GHz
   channels; see `regulatory-and-band.md`.
5. Check band support — a 2.4 GHz-only client cannot see a 5 GHz or 6 GHz-only
   SSID, and a 6 GHz SSID requires Wi-Fi 6E hardware.
6. Check the client's own radio: rfkill, airplane mode, or a disabled
   interface.
