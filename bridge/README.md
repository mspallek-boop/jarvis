# JARVIS Bridge

Die native Apple-App spricht ausschließlich mit diesem kleinen Dienst. Der
Hermes-API-Schlüssel bleibt auf dem Mac; iPhone und Mac-App verwenden einen
eigenen, widerrufbaren `JARVIS_APP_TOKEN`.

```bash
python3 bridge/jarvis_bridge.py --generate-token
```

Trage den erzeugten Wert sowie einen eigenen Hermes-API-Key in
`~/.hermes/.env` ein:

```dotenv
API_SERVER_ENABLED=true
API_SERVER_KEY=<langer-zufälliger-hermes-key>
JARVIS_APP_TOKEN=<langer-zufälliger-app-token>
JARVIS_FILE_ROOTS=/Users/marlon
```

Danach Hermes und Bridge starten:

```bash
hermes gateway start
python3 bridge/jarvis_bridge.py --host 0.0.0.0 --port 8770
```

Für Zugriff außerhalb des eigenen WLANs wird Tailscale empfohlen. Keine Ports
am Router öffnen. In der App dann die private Tailscale-Adresse des Macs
eintragen.

Die Bridge kann sicher an Loopback gebunden und über Tailscale Serve als HTTPS
bereitgestellt werden:

```bash
python3 bridge/jarvis_bridge.py --host 127.0.0.1 --port 8770
tailscale serve --bg 8770
```

Die Dateiansicht ist auf `JARVIS_FILE_ROOTS` begrenzt. Versteckte Dateien,
Hermes-Schlüssel, SSH-Schlüssel und Zertifikate bleiben unabhängig davon
gesperrt.
