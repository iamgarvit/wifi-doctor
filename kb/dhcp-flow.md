# The DHCP flow

DHCP runs **after** the link is encrypted and up. Anything here is a layer 3
problem; the Wi-Fi association itself already succeeded.

The four-message exchange (DORA):

```
dhclient: DHCPDISCOVER on wlan0 to 255.255.255.255 port 67 interval 5
dhclient: DHCPOFFER of <IPV4_1> from <IPV4_2>
dhclient: DHCPREQUEST for <IPV4_1> on wlan0 to 255.255.255.255 port 67
dhclient: DHCPACK of <IPV4_1> from <IPV4_2>
dhclient: bound to <IPV4_1> -- renewal in 1707 seconds.
```

NetworkManager wraps this and logs its own view:

```
NetworkManager: dhcp4 (wlan0): activation: beginning transaction (timeout in 45 seconds)
NetworkManager: device (wlan0): state change: config -> ip-config
```

## Failure

```
dhclient: No DHCPOFFERS received.
NetworkManager: dhcp4 (wlan0): state changed no lease
NetworkManager: device (wlan0): state change: ip-config -> failed (reason 'ip-config-unavailable')
```

The `DHCPDISCOVER` retry intervals back off (3, 7, 13, 21 …). Repeated
DISCOVERs with no OFFER means the request is not reaching a DHCP server or the
answer is not coming back.

Causes: DHCP pool exhausted, the AP's guest/client isolation blocking the
broadcast, no DHCP server on that VLAN, or wired-side problems behind the AP.
A 169.254.x.x address (`avahi`, link-local) appearing afterwards confirms no
lease was obtained.

**Key check:** if the log contains `CTRL-EVENT-CONNECTED` and a completed key
negotiation, Wi-Fi is fine. Do not diagnose a Wi-Fi fault for a DHCP failure.
