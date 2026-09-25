# IEEE 802.11 status codes

Status codes appear in Authentication and (Re)Association **response** frames —
the AP telling the client whether it may proceed. `0` means success; anything
else is a refusal.

```
kernel: wlan0: RX AssocResp from <MAC_1> (capab=0x1431 status=17 aid=0)
wpa_supplicant: wlan0: CTRL-EVENT-ASSOC-REJECT bssid=<MAC_1> status_code=17
```

Values are from **IEEE 802.11-2020, Table 9-50 (Status codes)**. Commonly seen
subset:

| Code | Meaning |
|---|---|
| 0 | Successful |
| 1 | Unspecified failure |
| 10 | Cannot support all requested capabilities in the Capability Information field |
| 11 | Reassociation denied due to inability to confirm that an association exists |
| 12 | Association denied due to a reason outside the scope of this standard |
| 13 | Responding STA does not support the specified authentication algorithm |
| 14 | Authentication frame received with a transaction sequence number out of expected sequence |
| 15 | Authentication rejected because of challenge failure |
| 16 | Authentication rejected due to timeout waiting for next frame in sequence |
| 17 | Association denied because AP is unable to handle additional associated STAs |
| 18 | Association denied because the requesting STA does not support all of the data rates in the BSSBasicRateSet |
| 27 | Association denied because the requesting STA does not support HT features |
| 30 | Association request rejected temporarily; try again later |
| 31 | Robust management frame policy violation |
| 37 | The request has been declined |
| 53 | Invalid PMKID |

## Reading them

- **17** and **30** are *load* answers: the AP is full or busy. Retrying, or a
  different BSS in the same ESS, usually works. Not a client misconfiguration.
- **12**, **1**, **37** are generic refusals — often an access-control list, a
  MAC filter, or a band-steering policy on the AP.
- **10**, **18**, **27** are *capability mismatches*: the AP requires something
  the client did not advertise.
- **53** means the client offered a PMKID the AP does not know; the client
  should fall back to a full authentication.
- Note the overlap with reason codes: a status code of 16 and a reason code of
  16 mean entirely different things. Always check which frame it came from.
