# Phase 2: Bewertung von `relay/` für den Cloud-Betrieb

Stand 2026-09-01, nachdem Phase 1 (iPhone → Tailscale → Mac-Bridge) verifiziert
ist. Diese Bewertung prüft, was der vorhandene Relay-Code im Cloud-Fall leistet
und was ihm fehlt.

## Kurzfassung

Der Relay ist zur Hälfte cloud-tauglich. Der Proxy-Teil funktioniert über
Tailscale unverändert. Der Weck-Teil ist im Cloud-Betrieb prinzipiell wirkungslos
und muss entfernt oder ersetzt werden. Zusätzlich fehlt dem Relay ein eigenes
Gehirn — er kann heute nur weiterleiten, nicht selbst antworten.

## Was der Relay heute tut

| Endpunkt | Verhalten |
|---|---|
| `GET /health` | meldet Relay-Status und ob die Mac-Bridge antwortet |
| `GET /files*` | `_ensure_awake()`, dann Proxy an die Mac-Bridge |
| `POST /wake` | sendet ein Wake-on-LAN-Magic-Packet |
| `POST /chat`, `/stop` | `_ensure_awake()`, dann Proxy an die Mac-Bridge |

## Was im Cloud-Betrieb bricht

**`_wake()` ist wirkungslos.** Die Funktion sendet ein UDP-Broadcast an
`JARVIS_MAC_BROADCAST` (z. B. `192.168.1.255`). Ein Broadcast erreicht nur das
lokale Netzsegment. Von einem Server bei Hetzner geht dieses Paket ins Leere.
Das ist keine Konfigurationsfrage, sondern eine Eigenschaft von Broadcasts.

**`_ensure_awake()` erbt den Defekt.** Es ruft `_wake()` und wartet dann bis zu
`JARVIS_WAKE_TIMEOUT` (Standard 90 s) darauf, dass der Mac antwortet. Im
Cloud-Fall wartet jede `/chat`-Anfrage an einen schlafenden Mac also 90 Sekunden
und scheitert anschließend. Das ist schlechter als ein sofortiger Fehler.

**Der Relay hat kein eigenes Gehirn.** Alle inhaltlichen Endpunkte sind reine
Weiterleitungen an die Mac-Bridge. Ist der Mac aus, kann der Relay nichts
beantworten — er meldet nur `Mac ist nicht erreichbar`. Das Ziel „JARVIS
antwortet auch bei ausgeschaltetem Mac" erfüllt der Relay in seiner heutigen
Form also nicht, unabhängig vom Hosting.

## Was unverändert funktioniert

**Der Proxy-Pfad.** `_mac_request()` spricht `JARVIS_MAC_BRIDGE_URL` an. Läuft
Tailscale auf dem Cloud-Server, ist die Mac-Bridge unter ihrer Tailnet-Adresse
erreichbar, und `_proxy()` arbeitet unverändert.

**Die Authentifizierung.** Derselbe App-Token wie auf dem Mac, gleiche Semantik.

**`GET /health`.** Die Unterscheidung `online` / `sleeping_or_off` ist im
Cloud-Fall sogar besonders nützlich, weil sie dem iPhone erlaubt, dem Nutzer den
Zustand ehrlich anzuzeigen.

## Nötige Änderungen für Phase 2

1. **Weck-Logik entfernen oder auslagern.** `_wake()`, `_ensure_awake()` und
   `POST /wake` sind im Cloud-Kontext irreführend. Entweder ersatzlos streichen,
   oder hinter eine Konfiguration stellen, die nur bei einem Relay im Heimnetz
   aktiv ist.
2. **Sofort scheitern statt 90 s warten.** Ist der Mac nicht erreichbar, gehört
   umgehend eine klare Antwort zurück, nicht ein langer Timeout.
3. **Eigenes Hermes auf dem Cloud-Knoten.** Für „antwortet immer" braucht der
   Server eine eigene Hermes-Instanz, an die der Relay weiterleitet, wenn der Mac
   fehlt. Das ist eine zusätzliche Komponente, keine Anpassung.
4. **Routing-Regel festlegen.** Der Relay muss entscheiden, wann er an den Mac
   und wann an das Cloud-Hermes weiterleitet. Naheliegend: Anfragen, die
   Mac-Dateien oder lokale Aktionen brauchen, gehen an den Mac; alles andere kann
   die Cloud beantworten.

## Offene Entscheidung: zwei Gehirne, zwei Gedächtnisse

Läuft Hermes sowohl auf dem Mac als auch in der Cloud, entstehen zwei getrennte
Sitzungs- und Gedächtnisspeicher. Ein Gespräch, das unterwegs in der Cloud
begonnen wurde, ist auf dem Mac nicht vorhanden und umgekehrt. Das ist der
wesentliche konzeptionelle Preis von Phase 2 und sollte vor dem Bau entschieden
werden — etwa durch einen gemeinsamen Sitzungsspeicher oder durch die bewusste
Festlegung, dass die Cloud nur kurze, kontextfreie Auskünfte gibt.

## Voraussetzungen, die noch fehlen

- Ein Cloud-Server (Hetzner o. ä.) ist noch nicht vorhanden.
- Tailscale müsste dort installiert und dem Tailnet beitreten.
- `JARVIS_MAC_BRIDGE_URL` zeigt dann auf die Tailnet-Adresse des Macs,
  Port 8770.

## Einschätzung

Phase 2 ist deutlich aufwendiger als Phase 1 und liefert weniger, als es auf den
ersten Blick wirkt: Der Cloud-Knoten kann den Mac nicht wecken und nicht auf
dessen Dateien zugreifen. Sein einziger echter Gewinn ist, dass überhaupt jemand
antwortet, während der Mac aus ist. Ob das den laufenden Aufwand und die
Trennung der Gedächtnisse rechtfertigt, ist eine Nutzungsfrage und sollte erst
nach einigen Tagen Praxiserfahrung mit Phase 1 entschieden werden.
