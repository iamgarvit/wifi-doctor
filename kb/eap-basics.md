# EAP and 802.1X basics

On an enterprise (WPA-Enterprise / 802.1X) network the PMK is not derived from
a passphrase. Instead, after association the client runs an **EAP** exchange
with a RADIUS server, relayed by the AP, and the PMK falls out of that.

Sequence in the log:

```
wlan0: CTRL-EVENT-EAP-STARTED EAP authentication started
wlan0: CTRL-EVENT-EAP-PROPOSED-METHOD vendor=0 method=25
wlan0: CTRL-EVENT-EAP-METHOD EAP vendor 0 method 25 (PEAP) selected
wlan0: EAP: Identity response: <IDENTITY_1>
wlan0: CTRL-EVENT-EAP-SUCCESS EAP authentication completed successfully
```

and only then does the 4-way handshake run.

## Failure

```
wlan0: CTRL-EVENT-EAP-FAILURE EAP authentication failed
kernel: wlan0: deauthenticated from <MAC_1> (Reason: 23=IEEE8021X_FAILED)
```

`CTRL-EVENT-EAP-FAILURE` plus Reason 23 is unambiguous: the RADIUS server
rejected this client. The 4-way handshake is never reached, so a passphrase
diagnosis is impossible by construction.

The usual causes, in order of frequency: wrong username or password, an expired
or wrong client certificate, an untrusted server certificate (the client
refuses the server, not the other way around), a user account outside the
policy group the RADIUS server allows, or an anonymous-identity/realm mismatch.

**Identities are usernames.** `EAP: Identity response:` and `identity=` lines
carry a real person's account name and must be redacted before any log leaves
the machine.
