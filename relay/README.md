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
```

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
