# IEEE 802.11 reason codes

Reason codes appear in Deauthentication and Disassociation frames. A Linux
client surfaces them two ways:

```
kernel: wlan0: deauthenticated from <MAC_1> (Reason: 15=4WAY_HANDSHAKE_TIMEOUT)
wpa_supplicant: wlan0: CTRL-EVENT-DISCONNECTED bssid=<MAC_1> reason=15
```

`locally_generated=1` on the `CTRL-EVENT-DISCONNECTED` line means **the client
sent the deauth**, not the AP. Without it, the AP kicked the client off. This
single flag decides between "the client gave up" and "the AP ejected us".

Values below are from **IEEE 802.11-2020, Table 9-49 (Reason codes)**. This is
the commonly seen subset, not the full table.

| Code | Meaning |
|---|---|
| 1 | Unspecified reason |
| 2 | Previous authentication no longer valid |
| 3 | Deauthenticated because sending STA is leaving (or has left) the BSS |
| 4 | Disassociated due to inactivity |
| 5 | Disassociated because AP is unable to handle all currently associated STAs |
| 6 | Class 2 frame received from nonauthenticated STA |
| 7 | Class 3 frame received from nonassociated STA |
| 8 | Disassociated because sending STA is leaving the BSS |
| 9 | STA requesting (re)association is not authenticated with responding STA |
| 13 | Invalid element |
| 14 | Message integrity code (MIC) failure |
| 15 | 4-way handshake timeout |
| 16 | Group key handshake timeout |
| 17 | Element in 4-way handshake differs from (Re)Association Request/Probe Response/Beacon |
| 18 | Invalid group cipher |
| 19 | Invalid pairwise cipher |
| 20 | Invalid AKMP |
| 23 | IEEE 802.1X authentication failed |
| 24 | Cipher suite rejected because of the security policy |
| 34 | Disassociated because of excessive missing ACKs |

## Reading them

- **15** and **16** are *timeouts*, not credential rejections. See
  `troubleshoot-handshake-timeout.md`.
- **23** is an 802.1X/EAP rejection — an enterprise credential or certificate
  problem, never a PSK problem.
- **1, 3, 4, 5, 8** from the AP with no other error usually mean the AP ended a
  working session: idle timeout, client limit, or an admin action.
- **14** (MIC failure) is a TKIP-era countermeasure and is rare on modern gear.
