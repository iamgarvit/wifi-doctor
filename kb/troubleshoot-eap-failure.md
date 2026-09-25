# Troubleshooting: EAP_FAILURE

**Class:** `EAP_FAILURE` — 802.1X/EAP authentication was rejected on an
enterprise network. Nothing to do with a Wi-Fi passphrase.

## Signature

```
wlan0: CTRL-EVENT-EAP-STARTED EAP authentication started
wlan0: CTRL-EVENT-EAP-METHOD EAP vendor 0 method 25 (PEAP) selected
wlan0: EAP: Identity response: <IDENTITY_1>
wlan0: CTRL-EVENT-EAP-FAILURE EAP authentication failed
kernel: wlan0: deauthenticated from <MAC_1> (Reason: 23=IEEE8021X_FAILED)
wlan0: CTRL-EVENT-SSID-TEMP-DISABLED id=0 ssid="<SSID_1>" auth_failures=1 duration=10 reason=AUTH_FAILED
```

`CTRL-EVENT-EAP-FAILURE` is unambiguous. Reason 23 and `reason=AUTH_FAILED`
corroborate it. The presence of *any* `CTRL-EVENT-EAP-*` line means this is an
enterprise network and rules out a PSK diagnosis.

Where it failed inside the EAP exchange narrows the cause further: see
`eap-methods.md`. A failure immediately after
`status='remote certificate verification'` is the client rejecting the
server's certificate; a failure after the tunnel is established is the server
rejecting the user's credentials.

## Fixes

1. Verify the username and password, including the realm
   (`user@example.edu` vs bare `user`).
2. Check the account is not locked, expired, or outside the group the RADIUS
   policy permits.
3. Check the CA certificate configured on the client, and
   `domain_suffix_match` / `ca_cert` settings — a missing CA makes a correct
   server look untrusted.
4. For EAP-TLS, check the client certificate's validity dates and that its
   private key is present and readable.
5. Check the RADIUS server logs; they state the rejection reason directly,
   which the client is never told.
