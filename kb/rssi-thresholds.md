# Signal strength, noise and SNR

wpa_supplicant reports link quality as:

```
wlan0: CTRL-EVENT-SIGNAL-CHANGE above=0 signal=-78 noise=-92 txrate=6000
```

- `signal` — received power in **dBm**. Always negative; closer to zero is
  stronger. A 3 dB change is a factor of two in power.
- `noise` — the noise floor in dBm, typically −90 to −95 dBm indoors.
- `above` — whether the signal is above the configured threshold (1) or below
  it (0). `above=0` is the client telling you it considers the link weak.
- `txrate` — current transmit rate in kbps. A collapse to `6000` (6 Mbps, the
  lowest OFDM rate) is the driver falling back to the most robust modulation,
  which is itself a symptom of a bad link.

## Operating thresholds

These are industry design conventions, not values from the standard:

| Signal | Assessment |
|---|---|
| ≥ −50 dBm | excellent, right next to the AP |
| −50 to −60 dBm | very good, full rates |
| −60 to −67 dBm | good; −67 dBm is the usual design target for voice and video |
| −67 to −70 dBm | marginal; expect rate drops and retries |
| −70 to −80 dBm | poor; handshakes and DHCP start timing out |
| ≤ −80 dBm | effectively unusable; association may succeed and then fail |

**SNR = signal − noise.** SNR ≥ 25 dB is good, 15–25 dB is workable, and below
about 10 dB the link will not carry useful traffic even if `signal` looks
survivable. A −75 dBm signal with a −92 dBm noise floor (17 dB SNR) behaves far
better than −75 dBm with a −80 dBm noise floor (5 dB SNR).

## Why this matters for diagnosis

Signal strength is the main tiebreaker between *credential* failures and
*link-quality* failures. A handshake that fails at −45 dBm is not a range
problem. A handshake that fails at −85 dBm very probably is.
