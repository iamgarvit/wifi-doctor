# The WPA 4-way handshake

After association, the AP (authenticator) and client (supplicant) run a
four-message EAPOL-Key exchange to prove they both hold the PMK and to derive
the session keys.

| Message | Direction | Contents |
|---|---|---|
| 1/4 | AP → client | ANonce |
| 2/4 | client → AP | SNonce + MIC (proves the client has the PMK) |
| 3/4 | AP → client | GTK + MIC (proves the AP has the PMK) |
| 4/4 | client → AP | acknowledgement |

Both sides derive the **PTK** from `PMK + ANonce + SNonce + both MAC
addresses`. For WPA2-Personal the PMK comes from the passphrase and the SSID;
for enterprise it comes from the EAP method (see `eap-basics.md`).

Success looks like:

```
wlan0: WPA: Key negotiation completed with <MAC_1> [PTK=CCMP GTK=CCMP]
wlan0: State: 4WAY_HANDSHAKE -> GROUP_HANDSHAKE
```

## Two very different failures

**A wrong passphrase** means the client's PMK is wrong, so the MIC on message
2/4 does not verify. The AP simply stops answering, and the client eventually
gives up and prints:

```
wlan0: WPA: 4-Way Handshake failed - pre-shared key may be incorrect
```

**A weak or lossy link** means the EAPOL-Key frames are lost in the air. The
client retries, logs `WPA: EAPOL-Key timeout`, and is deauthenticated with
Reason 15.

> **Critical:** wpa_supplicant prints the *same* "pre-shared key may be
> incorrect" message in both cases, because from its point of view it cannot
> tell them apart. That message on its own is **not** proof of a wrong
> passphrase. See `disambiguation-guide.md`.
