# Troubleshooting: DHCP_TIMEOUT

**Class:** `DHCP_TIMEOUT` — the Wi-Fi link came up completely and the client
then failed to obtain an IPv4 address.

## Signature

```
wlan0: WPA: Key negotiation completed with <MAC_1> [PTK=CCMP GTK=CCMP]
wlan0: CTRL-EVENT-CONNECTED - Connection to <MAC_1> completed [id=0 id_str=]
NetworkManager: device (wlan0): state change: config -> ip-config
dhclient: DHCPDISCOVER on wlan0 to 255.255.255.255 port 67 interval 3
dhclient: DHCPDISCOVER on wlan0 to 255.255.255.255 port 67 interval 7
dhclient: DHCPDISCOVER on wlan0 to 255.255.255.255 port 67 interval 21
dhclient: No DHCPOFFERS received.
NetworkManager: dhcp4 (wlan0): state changed no lease
```

The decisive combination is a **successful** layer 2 connection followed by
repeated `DHCPDISCOVER` with backing-off intervals and no `DHCPOFFER`.

This is the class most often misdiagnosed as a Wi-Fi fault. If the log contains
`CTRL-EVENT-CONNECTED`, the Wi-Fi worked.

## Fixes

1. Check the DHCP server is running and its pool is not exhausted.
2. Check client/guest isolation on the AP — some configurations block the
   broadcast `DHCPDISCOVER` between clients and the server's VLAN.
3. Check VLAN tagging between the AP and the switch; a mis-tagged SSID lands
   clients on a VLAN with no DHCP server.
4. Confirm with a static IP: if a manually configured address can reach the
   gateway, layer 2 is definitively fine and the problem is the DHCP service.
5. Check for a rogue DHCP server answering with an unusable lease (a
   `DHCPOFFER` from an unexpected address).
