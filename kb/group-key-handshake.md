# The group key handshake

After the 4-way handshake the AP distributes the **GTK** (group temporal key),
used for broadcast and multicast traffic. It is refreshed periodically and
whenever a client leaves the BSS, so this exchange happens repeatedly during a
long session, not only at connect time.

```
wlan0: State: 4WAY_HANDSHAKE -> GROUP_HANDSHAKE
wlan0: State: GROUP_HANDSHAKE -> COMPLETED
```

A failure here produces **Reason 16 (Group key handshake timeout)**. It looks
like a mid-session drop on an otherwise healthy link and is almost always a
link-quality or AP-firmware problem, never a credential problem — the client
had already proved it held the PMK to get this far.

If a client repeatedly disconnects with Reason 16 at good signal, suspect the
AP's group-rekey interval or a driver bug, and try raising the rekey interval
on the AP as a diagnostic.
