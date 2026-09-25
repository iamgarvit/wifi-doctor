# Common EAP methods

`CTRL-EVENT-EAP-PROPOSED-METHOD vendor=0 method=N` and
`CTRL-EVENT-EAP-METHOD ... method N (NAME) selected` carry the EAP method type
number assigned by IANA.

| Method | Name | Credential | Notes |
|---|---|---|---|
| 13 | EAP-TLS | client certificate | strongest; fails if the client cert is missing or expired |
| 21 | EAP-TTLS | username/password inside a TLS tunnel | inner method often PAP or MSCHAPv2 |
| 25 | PEAP | username/password inside a TLS tunnel | inner method usually MSCHAPv2 |
| 18 | EAP-SIM | SIM card | carrier Wi-Fi offload |
| 23 | EAP-AKA | USIM | carrier Wi-Fi offload |
| 43 | EAP-FAST | PAC or credentials | Cisco-originated |

All the tunnelled methods validate the **server's** certificate first:

```
wlan0: CTRL-EVENT-EAP-STATUS status='remote certificate verification' parameter=''
wlan0: CTRL-EVENT-EAP-PEER-CERT depth=0 subject='/CN=radius.example.com'
```

If the log stops at `remote certificate verification` and then fails, the
client rejected the RADIUS server's certificate — a CA or `domain_suffix_match`
configuration problem on the client, not a bad password. If the log gets past
the certificate and *then* fails, the credentials themselves were rejected.
