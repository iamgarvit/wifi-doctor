# Troubleshooting: WRONG_PASSWORD

**Class:** `WRONG_PASSWORD` — the configured WPA2-Personal passphrase does not
match the one the AP expects.

## Signature

```
wlan0: State: ASSOCIATED -> 4WAY_HANDSHAKE
wlan0: CTRL-EVENT-SIGNAL-CHANGE above=1 signal=-47 noise=-92 txrate=130000
wlan0: WPA: 4-Way Handshake failed - pre-shared key may be incorrect
wlan0: CTRL-EVENT-DISCONNECTED bssid=<MAC_1> reason=15 locally_generated=1
wlan0: CTRL-EVENT-SSID-TEMP-DISABLED id=0 ssid="<SSID_1>" auth_failures=2 duration=20 reason=WRONG_KEY
```

The decisive combination is:

- association and 802.11 authentication both **succeed** — the failure is in
  the 4-way handshake, not before it;
- **strong signal** at the moment of failure;
- **no** `WPA: EAPOL-Key timeout` lines;
- repeated attempts with a **rising `auth_failures=N`**;
- ideally `reason=WRONG_KEY` on the temp-disable line.

`reason=WRONG_KEY` alone is sufficient. Without it, rely on the strong signal
plus the rising counter. See `disambiguation-guide.md` for why the
"pre-shared key may be incorrect" message alone is not sufficient.

## Fixes

1. Re-enter the passphrase; check for a trailing space, a smart quote pasted
   from a chat app, or the wrong case.
2. Forget the network and re-add it, to clear a stale stored PSK.
3. Confirm the passphrase against the AP itself — it may have been rotated.
4. Check the security mode matches (a WPA3-only AP with a WPA2-only client
   fails differently; see `sae-and-wpa3.md`).
5. If several clients fail at once, suspect the AP, not the client.
