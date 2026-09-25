# What counts as evidence

A diagnosis is only useful if a human can check it. Every claim must point at
specific lines in the log the user supplied.

## Rules

1. **Quote verbatim.** The quoted text must appear character-for-character in
   the cited line. Paraphrasing makes the citation uncheckable.
2. **Cite the line number that contains the quote**, 1-based, as printed by the
   search and timeline tools.
3. **Prefer control events and kernel frame-level lines** over free-text debug
   output; they are stable across versions.
4. **Corroborate across sources.** A supplicant line plus the matching kernel
   line is much stronger than either alone.
5. **Cite the discriminator, not just the symptom.** For a handshake timeout,
   the `EAPOL-Key timeout` line and the weak `signal=` line matter more than
   the generic failure message that also appears in the wrong-password case.
6. **Do not cite noise.** Lines from `CRON`, `bluetoothd`, `avahi-daemon`,
   `systemd` and similar have nothing to do with Wi-Fi.
7. **Do not invent lines.** If a line that would settle the question is not in
   the log, say so and set `needs_more_info`, rather than citing something that
   nearly says it.

## For a HEALTHY verdict

Cite the lines that prove success — `CTRL-EVENT-CONNECTED`, `WPA: Key
negotiation completed`, `DHCPACK` — and, if the log contains an earlier error,
cite the recovery that followed it. A confident "nothing is wrong" needs
evidence just as much as a failure does.

## Confidence

Report calibrated confidence. High confidence needs an unambiguous
discriminator (`reason=WRONG_KEY`, `CTRL-EVENT-EAP-FAILURE`, a non-zero
`status_code`). If the log is truncated before the decisive event, or two
classes remain equally consistent with it, the honest answer is a lower
confidence and `needs_more_info=true`.
