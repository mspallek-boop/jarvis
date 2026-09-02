# Phase 1: iPhone erreicht den Mac über Tailscale

In Phase 1 stellt die JARVIS-Bridge auf dem Mac seine Dienste ausschließlich über
Tailscale im Tailnet als HTTPS-Endpunkt bereit. Das iPhone verbindet sich direkt
mit dem wachen Mac — es gibt keinen Cloud-Server und kein Wake-on-LAN. Sobald der
Mac ausgeschaltet ist, ist kein Dienst mehr erreichbar; das wird erst in Phase 2
über einen Always-on-Relay-Knoten gelöst.

## Voraussetzungen

- Tailscale ist auf dem Mac und auf dem iPhone installiert und beide sind im
  selben Tailnet angemeldet.
- Ein HomePod steht im selben WLAN wie der Mac und dient als Bonjour Sleep Proxy.
- Der Mac läuft am Strom; auf Akku hält macOS den Netzwerk-Weckpfad nicht
  zuverlässig aufrecht.

## Einrichtung auf dem Mac

1. Tailscale installieren und mit demselben Konto anmelden wie auf dem iPhone,
   damit beide Geräte im selben Tailnet landen.
2. Prüfen, dass die Bridge läuft und den Service-Banner liefert:
   ```bash
   curl http://127.0.0.1:8770/
   ```
   Die Antwort muss den JARVIS-Bridge-Banner zurückgeben.
3. Die Bridge ist an `127.0.0.1:8770` gebunden und wird per Tailscale-Serve
   veröffentlicht — sie wird nicht auf `0.0.0.0` umgestellt, weil der Mac ein
   Notebook ist und sonst in fremden WLANs exponiert würde:
   ```bash
   tailscale serve --bg --http=8770 http://127.0.0.1:8770
   ```
   `--http` ist bewusst gewaehlt: TLS-Zertifikate (`tailscale serve --bg 8770`)
   setzen voraus, dass im Tailnet HTTPS Certificates aktiviert sind. Ohne das
   bleibt der Befehl ohne Ausgabe haengen, und `tailscale cert <name>` meldet
   "your Tailscale account does not support getting TLS certs". Der Verkehr ist
   auch ohne TLS geschuetzt, weil Tailscale ihn per WireGuard verschluesselt.
4. Mit `tailscale serve status` die entstandene URL ablesen. Sie hat die Form
   `http://<hostname>.<tailnet>.ts.net:8770` und ist nur im Tailnet erreichbar.

Authentifizierung erfolgt über den App-Token: der Client sendet entweder den
Header `Authorization: Bearer <JARVIS_APP_TOKEN>` oder `X-Jarvis-Token`.

## Einrichtung auf dem iPhone

1. Tailscale aus dem App Store installieren und mit demselben Konto anmelden
   wie auf dem Mac, damit beide Geräte dasselbe Tailnet teilen.
2. In der JARVIS-App die Tailscale-URL (`http://<hostname>.<tailnet>.ts.net:8770`)
   als Server eintragen.
3. denselben `JARVIS_APP_TOKEN` hinterlegen, der auch unter
   `~/.hermes/.env` auf dem Mac definiert ist.

## Wecken über den HomePod

Da der Mac WLAN-only ist (`en0`, kein Ethernet) und `pmset` `womp=0` zeigt, ist
Wake-on-LAN (Magic Packet) kein passender Weg: `womp` gilt im Wesentlichen für
Ethernet. Stattdessen nutzt Phase 1 Apples "Wake on Demand": der HomePod
(ebenso ein Apple TV) fungiert als Bonjour Sleep Proxy im selben WLAN.
Er übernimmt die Bonjour-Dienste des schlafenden Macs und weckt ihn, sobald ein
Gerät **im lokalen Netz** einen dieser Dienste anspricht. Voraussetzung ist, dass
der Mac am Strom hängt; auf Akku hält macOS den Weg nicht zuverlässig.

**Die entscheidende Einschränkung:** Dieser Weckpfad wirkt nur innerhalb des
lokalen Netzes. Tailscale selbst kann kein Wake-on-LAN-Paket senden, und eine
über Mobilfunk eingehende Tailscale-Verbindung erreicht einen schlafenden Mac
nicht — schläft der Mac, schläft auch sein Tailscale-Dienst. Ein Magic Packet
ist ein Broadcast im lokalen Netz; ein Cloud-Server könnte einen schlafenden Mac
also ohnehin nie wecken.

Praktische Folge: Wer unterwegs zuverlässig auf den Mac zugreifen will, lässt ihn
wach (Ruhezustand deaktiviert, am Strom) oder braucht ein Always-on-Gerät im
Heimnetz, das das Magic Packet sendet.

## Test

| Mac-Zustand | iPhone im selben WLAN | iPhone unterwegs (Mobilfunk) |
|---|---|---|
| wach | Bridge antwortet über die ts.net-URL (verifiziert); Chat und Dateizugriff funktionieren. | Ebenso: Tailscale verbindet direkt. |
| im Ruhezustand | Der HomePod kann den Mac wecken, sobald ein per Bonjour beworbener Dienst im LAN angesprochen wird. Danach antwortet die Bridge. | **Kein Zugriff.** Tailscale kann kein Wake-on-LAN-Paket senden, und der Sleep Proxy wirkt nur im lokalen Netz. |
| ausgeschaltet | Kein Zugriff. | Kein Zugriff. |

## Grenzen

Zwei Zustände liefern in Phase 1 keinen Zugriff:

- **Mac ausgeschaltet.** Weder Tailscale noch der HomePod können einen Mac wecken,
  der nicht mehr läuft.
- **Mac im Ruhezustand, iPhone unterwegs.** Der Sleep Proxy wirkt nur im lokalen
  Netz, und Tailscale sendet keine Magic Packets.

Für echte 24/7-Erreichbarkeit ist der Cloud-Knoten aus Phase 2 nötig. Er kann den
Mac zwar ebenfalls nicht wecken, aber selbst antworten, solange keine Mac-Dateien
oder -Aktionen gebraucht werden.
