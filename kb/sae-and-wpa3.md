# SAE and WPA3-Personal

WPA3-Personal replaces the PSK-based authentication of WPA2 with **SAE**
(Simultaneous Authentication of Equals, a dragonfly key exchange). It still
ends in a 4-way handshake, but the PMK is produced by SAE rather than derived
directly from the passphrase.

Consequences when reading logs:

- SAE runs inside the **802.11 Authentication** exchange, so a wrong WPA3
  passphrase fails at `AUTHENTICATING`, not at `4WAY_HANDSHAKE`. The log shows
  an authentication rejection or repeated SAE commit/confirm attempts, and
  wpa_supplicant may log `SME: SAE authentication failed`.
- Because of this, "wrong password" looks *different* on WPA3 than on WPA2.
  The familiar `WPA: 4-Way Handshake failed - pre-shared key may be incorrect`
  is a WPA2-Personal signature.
- SAE is resistant to offline dictionary attacks and provides forward secrecy,
  which is why WPA3 exists.
- **Transition mode** networks advertise both WPA2-PSK and WPA3-SAE. Clients
  that mis-negotiate here can produce Reason 20 (Invalid AKMP) or unexpected
  association rejections.

Management Frame Protection (802.11w / PMF) is mandatory for WPA3. A PMF
mismatch between client and AP shows up as association rejection or as
deauthentication frames being ignored.
