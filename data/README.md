# Synthetic data

**Every log in this directory is synthetic.** Nothing here was captured from a
real device, a real network, or a real person. There is no PII in the dataset
by construction — SSIDs, BSSIDs, hostnames, IP addresses and EAP identities are
drawn from small invented pools in `scripts/generate_logs.py`. (The redaction
layer in `src/wifi_doctor/redact.py` still runs on them, because it has to work
on the real logs a user pastes into the demo.)

## What the logs are modelled on

The *format* imitates what a Linux client actually writes to the system journal
during a Wi-Fi association:

| Source in the log | Modelled on |
|---|---|
| `wpa_supplicant[pid]: wlan0: ...` | wpa_supplicant control-interface events (`CTRL-EVENT-*`) and its `State: A -> B` machine |
| `kernel: wlan0: ...` | mac80211/cfg80211 messages (`send auth to ... (try 1/3)`, `RX AssocResp ... status=`, `deauthenticated from ... (Reason: N=NAME)`) |
| `NetworkManager[pid]: <info> [ts] ...` | NetworkManager device/dhcp4 state changes |
| `dhclient[pid]: ...` | ISC dhclient DHCP DISCOVER/OFFER/REQUEST/ACK flow |

Only control-event names, supplicant state names, IEEE 802.11 reason codes and
status codes that genuinely exist are used. Codes are those from
**IEEE 802.11-2020 Table 9-49 (Reason codes)** and **Table 9-50 (Status
codes)**; the subset used is listed in `kb/reason-codes.md` and
`kb/status-codes.md`. Message wording is a close imitation, not a byte-exact
reproduction of any particular wpa_supplicant version — treat the dataset as a
*format-faithful benchmark*, not as a replacement for real captures.

## Ground truth

Each case is one JSON object per line in `cases.jsonl`:

```jsonc
{
  "id": "test_0007",
  "split": "test",
  "root_cause": "HANDSHAKE_TIMEOUT",  // one of the 11 labels in schema.py
  "variant": "misleading",
  "seed": 77008152,
  "n_lines": 214,
  "evidence_lines": [88, 91, 93, 95],  // 1-based, recorded at emit time
  "entities": {"ssid": "...", "bssid": "...", "host": "...", "freq": 5180},
  "log": "Sep 25 19:04:12 ...\n..."
}
```

`evidence_lines` are recorded as the generator writes them, never recovered by
grepping afterwards, so they stay exact however much noise is interleaved.
`HEALTHY` cases have an empty `evidence_lines` list.

## Splits

| Split | Cases | Base seed | Use |
|---|---|---|---|
| `dev` | 44 | `20250925` | prompt and rule tuning |
| `test` | 66 | `77001313` | **held out** — reported numbers only |

Labels are balanced (4 per class in dev, 6 per class in test). Seeds are
disjoint, so no test log can be reproduced from a dev seed. The test split is
never used for prompt tuning; the README records which numbers came from it.

## Difficulty variants

The first pass over the label set is always `plain`, so every class has at
least one easy example. The rest are sampled:

- **`heavy_noise`** — 9–18 unrelated syslog lines between every phase.
- **`misleading`** — a real-looking but irrelevant error (a previous session
  ending, a transient `CTRL-EVENT-SCAN-FAILED`, a stray assoc-reject) is
  planted *before* the true failure and deliberately excluded from
  `evidence_lines`. Decoys that would collide with the case's own label are
  suppressed.
- **`truncated`** — log rotation cut the tail off.
- **`transient_recovery`** — an error occurs, the client *recovers and
  connects*, and only then does the real failure happen. A model that reports
  the first error it sees gets these wrong.

## The deliberate trap

`WRONG_PASSWORD` and `HANDSHAKE_TIMEOUT` are hard to separate on purpose,
because they are hard to separate in reality: wpa_supplicant prints

```
WPA: 4-Way Handshake failed - pre-shared key may be incorrect
```

for *any* 4-way handshake failure, including a pure timeout on a weak link. So
60% of `HANDSHAKE_TIMEOUT` cases contain that line too, and it is not marked as
evidence for them. What actually separates the classes is the combination the
knowledge base documents in `kb/troubleshoot-wrong-password.md`:

- `WRONG_PASSWORD` — strong RSSI (−58…−35 dBm), repeated attempts with a rising
  `auth_failures=N` counter, usually `reason=WRONG_KEY` on the
  `CTRL-EVENT-SSID-TEMP-DISABLED` line.
- `HANDSHAKE_TIMEOUT` — weak RSSI (−89…−76 dBm), `WPA: EAPOL-Key timeout`
  repeated, deauth `Reason: 15=4WAY_HANDSHAKE_TIMEOUT`, and **no**
  `reason=WRONG_KEY`.

Symmetrically, 20% of `WRONG_PASSWORD` cases omit the PSK message entirely and
must be identified from the counter and the signal strength alone.

## Regenerating

```bash
python scripts/generate_logs.py            # writes data/synthetic/{dev,test}/cases.jsonl
```

The generator is fully seeded: same seeds in, byte-identical logs out.
