# Always-on Relay

Der Relay läuft auf einem Gerät, das im selben Heimnetz wie der Mac dauerhaft
eingeschaltet ist: Raspberry Pi, NAS, Linux-Mini-PC oder Home-Assistant-Host.
Tailscale läuft auf Relay und iPhone; am Router wird kein Port geöffnet.

`/etc/jarvis-relay.env`:

```dotenv
JARVIS_APP_TOKEN=<derselbe-lange-token-wie-auf-dem-mac>
JARVIS_MAC_BRIDGE_URL=http://192.168.1.20:8770
JARVIS_MAC_ADDRESS=aa:bb:cc:dd:ee:ff
JARVIS_MAC_BROADCAST=192.168.1.255
JARVIS_WAKE_TIMEOUT=90
JARVIS_WAKE_ENABLED=1          # 0 on a cloud relay — see below
```

## Wake-on-LAN is LAN-only

A magic packet is a UDP broadcast and is never routed off its own network
segment. A relay on a VPS therefore cannot wake the Mac, no matter how it is
configured. `JARVIS_WAKE_ENABLED` controls this explicitly:

- unset — waking is enabled when `JARVIS_MAC_ADDRESS` is set (home relay)
- `0` — waking off; `POST /wake` answers `501` and `/chat` fails immediately
  instead of blocking for `JARVIS_WAKE_TIMEOUT` on a request that cannot succeed
- `1` — force on

`GET /health` reports `wake_enabled`, so the app can hide a "wake the Mac"
button on a relay that has no such power.

On a MacBook, waking also needs the real hardware MAC of the active interface —
a randomised ("Private Wi-Fi Address") MAC changes per network and will not
match the packet — plus Wake-for-network-access enabled, and sleep rather than
shutdown. Over Wi-Fi this is unreliable in practice; Ethernet is the dependable
path.

Die Mac-Adresse muss zur aktiven Netzwerkschnittstelle gehören. Für ein
MacBook ist Ruhezustand statt Ausschalten vorgesehen. Wake-on-LAN kann keinen
vollständig ausgeschalteten Mac zuverlässig starten.

Installation auf einem Linux-Relay:

```bash
sudo mkdir -p /opt/jarvis
sudo cp -R relay /opt/jarvis/
sudo cp relay/jarvis-relay.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now jarvis-relay
```

In der JARVIS-App wird anschließend die Tailscale-Adresse des Relays verwendet,
zum Beispiel `http://100.80.10.4:8787`.
