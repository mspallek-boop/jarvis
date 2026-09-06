# Relay-Delta und Lösung für JARVIS in der Cloud

Stand: 2026-09-05. Autoritatives Repo: `/Users/marlon/Documents/JARVIS`,
Branch `checkpoint/bridge-port-8770`. Abgleich mit `TARGET_ARCHITECTURE.md`.
Diese Fassung ersetzt die Bewertung vom 2026-09-01. Sie beschreibt den aktuellen
Code und einen noch nicht implementierten Cloud-Ausbau; kein Deployment erfolgt.

## Ergebnis

`relay/` kann authentifiziert den Bridge-Status prüfen, im Heimnetz ein
Wake-Paket senden und Requests an den Mac weiterleiten. Ein Cloud-Relay allein
liefert keinen Chat bei ausgeschaltetem Mac. Dafür braucht JARVIS einen
Cloud-Core mit eigener Hermes-Instanz. Der Wake-Sender bleibt im Heimnetz.

Die frühere Forderung, Cloud-Wake abzuschalten und die 90-Sekunden-Warteschleife
zu vermeiden, ist bereits umgesetzt: `JARVIS_WAKE_ENABLED=0` liefert für `/wake`
501 und bei unerreichbarem Mac für `/chat` 503, nach der Health-Prüfung mit
3-Sekunden-Timeout. Es fehlt kein weiterer Schalter dafür.

Die vom Nutzer verifizierte Mac-Verbindung lautet:
`https://macbook-air-von-marlon.tailfb3c35.ts.net:8443` → Tailscale Serve →
`127.0.0.1:8770`. Die bestehende Verbindung wurde in diesem Arbeitspaket nicht
live erneut aufgerufen oder umkonfiguriert.

## Delta zur Zielarchitektur

| Ziel | Befund im Repo | Noch nötig |
|---|---|---|
| Always-on-Knoten | `jarvis-relay.service:11` startet den Dienst nach Fehlern neu. Ein laufender Host ist damit nicht nachgewiesen. | Cloud-Host und Heimnetz-Wake-Knoten bereitstellen, Neustart und Tailnet-Verbindung verifizieren. |
| Nur über Tailscale erreichbar | CLI (`jarvis_relay.py:221`) und Unit (`jarvis-relay.service:10`) binden an `0.0.0.0:8787`. | Deployment an Loopback hinter Serve oder explizit an die Tailnet-IP binden. Der vorhandene Default erzwingt keine Tailnet-Isolation. Kein Router-Port-Forwarding. |
| Richtige Mac-Adresse | Default ist `http://jarvis.local:8770` (`jarvis_relay.py:43`); README verwendet eine LAN-IP. | `JARVIS_MAC_BRIDGE_URL` auf die oben verifizierte HTTPS-Adresse mit Port 8443 setzen. Die Bridge lauscht nur auf Loopback; eine LAN-IP mit 8770 passt nicht zu diesem Betrieb. |
| Mac-Status melden | `_mac_online()` (`:97`) wertet HTTP 200 aus; jede Exception wird zu `sleeping_or_off`. | Transport, Auth-Fehler, Bridge und Hermes unterscheiden. 401, TLS-/DNS-Fehler oder Hermes-503 beweisen keinen Schlafzustand. `unknown/unreachable` statt erfundenem Energiezustand; Health-Inhalt auswerten. |
| Authentifiziertes Wake | GET/POST prüfen Bearer-Token vor den Aktionen (`:148`, `:174`); `hmac.compare_digest`, mindestens 24 Zeichen. `/wake` sendet drei Pakete (`:104`). | Auf dem tatsächlichen Heimnetz-Knoten und Mac testen. HTTP 200 bestätigt nur das Senden, nicht das Aufwachen. Das UDP-Paket selbst hat keine Bearer-Authentifizierung. |
| Cloud kann Wake auslösen | Cloud-Wake lässt sich korrekt deaktivieren; `_wake()` sendet ausschließlich lokalen Broadcast. | Cloud-Gateway muss einen fest konfigurierten Heimnetz-Wake-Dienst authentifiziert über Tailscale aufrufen. Diese Weiterleitung fehlt im Relay. |
| Keine Hermes-Schlüssel auf Handy/Relay | Relay verwendet ausschließlich `JARVIS_APP_TOKEN` (`:42`, `:90`). | Beibehalten. Für Cloud-Hermes einen eigenen Schlüssel nur auf dessen Core-Host verwenden; nie den Mac-Hermes-Key kopieren. |
| Chat bei ausgeschaltetem Mac | `/chat` und `/stop` gehen immer über `_ensure_awake()` und `_proxy()` zum Mac (`:201`). | Eigener Cloud-Core, persistente Gespräche und gezielte Mac-Tools. Kein automatisches Wiederholen eines möglicherweise schon ausgeführten Mac-Auftrags in einem zweiten Hermes. |
| Dateizugriff nach Bridge-Vertrag | `/files*` wird weitergereicht; Roots kontrolliert die Mac-Bridge. `_proxy()` (`:133`) puffert die gesamte Antwort und macht aus jedem Upstream-HTTP-Fehler 502. | Exakte Routen, begrenztes/gestreamtes Download-Verhalten, passende Fehlercodes (insbesondere 403/404) und `Content-Disposition` erhalten. Mac-Dateien bleiben offline ohne ausdrücklich eingerichtete Synchronisierung. |

## Vor einem Relay-Deployment beheben

1. **Private Bindung und Dienstkonto:** Unit und README auf den konkreten
   Serve-Betrieb abstimmen. Die System-Unit enthält kein `User=` und würde als
   Systemdienst standardmäßig mit Root-Rechten laufen. Ein unprivilegierter
   Dienst mit gezieltem Zugriff auf seine Konfiguration reicht aus.
2. **Konfiguration und Requests validieren:** `wake_enabled=1` akzeptiert auch
   eine fehlende MAC-Adresse. Negative `Content-Length`-Werte gelangen an
   `rfile.read(length)` (`:178–185`) und können bis zum Verbindungsende warten;
   ungültige Längen werden still zu 0. MAC, Port, Timeouts und Body-Längen vor
   Nutzung prüfen, Lese-Timeout und Parallelitätsgrenzen vorsehen. Socket-Fehler
   beim Wake konsistent in JSON abbilden; beim GET-Dateipfad fehlt außerdem das
   Abfangen eines Wake-`ValueError`.
3. **Feste Upstream-Grenzen:** `_mac_request()` nutzt `urlopen` mit dessen
   Standard-Redirect-Verhalten. Vor Erweiterung um Cloud/Wake-Ziele nur feste
   private Ziele erlauben und Redirects ablehnen, damit kein Bearer-Header an
   ein umgeleitetes Ziel weitergereicht werden kann.
4. **Abbruch und Wartezeiten:** `/stop` sollte einen bekannten Auftrag direkt
   abbrechen können, statt einen Mac zu wecken. Die App wartet aktuell 120 s
   auf Chat und 20 s auf Dateien (`JarvisAPIClient.swift`); Relay-Wake plus
   Bridge-Chat kann diese Werte überschreiten. Status/Job-ID und Cancellation
   über `client_run_id` durchgängig implementieren. Kein blindes Retry von
   Schreibaktionen.
5. **Datensparsame Logs:** Die Standard-Request-Zeile wird geloggt (`:67`).
   Dateipfade in Query-Parametern können dadurch im Journal landen. Methode,
   Route, Status und Request-ID genügen; keine Header, Query-Werte oder Bodies.

Diese Punkte wurden statisch geprüft, nicht durch Angriffe auf laufende Dienste.
Die Produktions-Sicherheitsposture wurde für die Tests nicht verändert.

## Vorgeschlagene Cloud-Lösung

```text
iPhone / native Mac-App
  │ HTTPS über Tailscale, App-Token
  ▼
Cloud-Gateway (nur privater Eingang)
  ├── lokaler Core-Adapter → Cloud-Hermes → persistente Gespräche
  │                         eigener Hermes-Key bleibt beim Core
  ├── feste Mac-Tools → Tailscale → Mac-Bridge → lokales Hermes
  │                                        Kalender / Erinnerungen / Dateien
  └── authentifiziertes /wake → Tailscale → Heimnetz-Wake-Knoten
                                           └── lokales Magic Packet → Mac
```

Der Cloud-Core wird das primäre Gesprächssystem. Der Mac übernimmt klar
begrenzte lokale Aufgaben, beispielsweise Kalender lesen, Erinnerungen und
freigegebene Dateien. Dadurch bleibt ein Gespräch auch bei schlafendem Mac
vorhanden. Ein stiller Wechsel zwischen zwei unabhängigen Chat-Speichern entfällt.
Das ist eine Architekturentscheidung für den Ausbau, keine bereits vorhandene
Funktion. Die Mac-Bridge bietet heute noch keinen typisierten Tool-Vertrag dafür.

Schlüsselgrenzen: Das Handy kennt nur seinen App-Token. Das Gateway erhält
begrenzte Service-Tokens für Core-Adapter, Mac-Tools und Wake-Dienst. Der
Heimnetz-Wake-Dienst soll nur seinen Wake-Token kennen. Hermes-API-Keys werden
nur vom jeweiligen lokalen Core-/Bridge-Prozess verwendet. Diese Trennung
braucht neue Token-Konfiguration und Routen; der aktuelle Relay verwendet noch
einen gemeinsamen App-Token für Eingang und Mac-Ausgang.

Tailscale Serve kann lokale Dienste innerhalb des Tailnets bereitstellen.
Tailnet-Regeln sollen nur App → Gateway, Gateway → Mac-Bridge und Gateway →
Wake-Dienst erlauben. Hermes selbst bleibt auf Loopback; die konkreten
Identitäten/Tags müssen aus dem später gewählten Deployment stammen.
Quellen: [Tailscale Serve](https://tailscale.com/docs/features/tailscale-serve),
[Policy-Syntax](https://tailscale.com/docs/reference/syntax/policy-file).

Der vorhandene Broadcast-Sender braucht ein Gerät im Heimnetz. Tailscale ersetzt
keine Ethernet-Broadcast-Domäne. Auch eine Cloud mit Tailnet-Zugang kann diesen
Sender nicht direkt ersetzen. Quelle:
[Tailscale: Wake-on-LAN mit einem Raspberry Pi](https://tailscale.com/blog/wake-on-lan-tailscale-upsnap).

## Umsetzungsreihenfolge und Abnahme

1. **Cloud-Chat:** Core-Adapter und eigene Hermes-Instanz auf einem dauerhaft
   laufenden Host; private Gateway-Verbindung; Gesprächsspeicher und Backup.
   Abnahme: Mac offline, App-Chat antwortet; Gespräch bleibt nach Core-Neustart
   erhalten. Keine Mac-Aktion wird als erfolgreich behauptet, wenn der Mac fehlt.
2. **Heimnetz-Wake:** Relay auf Status/Wake begrenzen, eigenes Dienstkonto und
   Wake-Token, oben genannte Eingabe- und Netzwerkgrenzen. Abnahme: fehlender oder
   falscher Token sendet kein Paket; gültiger Token sendet am festgelegten
   Interface; schlafender Mac wird erreichbar; ausgeschalteter/unverfügbarer Mac
   liefert einen begrenzten Timeout mit ehrlichem Status.
3. **Mac-Tools:** feste Operationen und Roots, Request-ID, idempotente Behandlung
   wiederholter Aufträge, Ergebnisrückgabe an das Cloud-Gespräch. Kalender nur
   über `/Users/marlon/.hermes/bin/jarvis-cal`, Erinnerungen über `remindctl`.
   Abnahme: Cloud-Auftrag liest echte Kalenderdaten; Abbruch und Verbindungsverlust
   verursachen keine doppelte Aktion. Kein Reminders-AppleScript, kein icalBuddy.
4. **Native App:** getrennte Anzeige von Core/Mac/Wake, passender Standard-Endpunkt
   (derzeit im `AppModel.swift` noch HTTP auf 8770), Sprachberechtigung ohne
   Wiederholungsschleife, deutsche Stimme, Aufnahme/Antwort/Unterbrechung als
   klarer Zustandsablauf. Abnahme auf echtem Mac und iPhone inklusive verweigerter
   Berechtigung, Neustart, Hintergrundwechsel und laufender Sprachantwort.

## Verifikation dieses Arbeitspakets

- `PYTHONPYCACHEPREFIX=/tmp/jarvis-pycache .venv/bin/python -m pytest -q`:
  110 Tests bestanden, vor und nach den Änderungen. `pytest.ini` sammelt nur
  `tests/`; diese Zahl umfasst weder Bridge- noch Relay-Tests.
- Open-Meteo-Allowlist war bereits vorhanden, mit HUD-Wetter-Kommentar.
  `server/hud/index.html:812` verwendet `/v1/forecast` mit konfigurierten
  Koordinaten und Zeitzone; dort werden keine Tokens oder Chat-Inhalte angehängt.
- Der Dashboard-Test hatte bereits einen Backend-Stub. Nun sind exakte
  200-Antwort, Stub-Inhalt und Backend-Aufruf geprüft; der 401-Gegenfall prüft,
  dass der Backend-Stub nicht aufgerufen wurde.
- `tests/conftest.py` blockiert echte IP-Verbindungen, IP-Senden und DNS auch
  gegen Loopback. Aufgefangene Netzwerkfehler lassen den Test trotzdem am
  Teardown scheitern. In-Process-ASGI und lokale Unix-Socketpairs bleiben nutzbar.
  Lokale `.env`-Dateien werden beim Server-Import übersprungen; Sitzungs-,
  Nutzungs- und Log-Dateien liegen pro Test im temporären Verzeichnis.
- Ein temporärer Negativtest versuchte eine Verbindung zu `127.0.0.1:9119`
  und fing den Fehler ab: Die Sperre machte den Test erwartungsgemäß rot.
  Der Negativtest wurde anschließend automatisch entfernt.
- `PYTHONPYCACHEPREFIX=/tmp/jarvis-pycache .venv/bin/python -m pytest -q relay/test_relay.py`:
  14 Tests bestanden, mit gemocktem Netzwerk und Wake. Sechs neue Tests prüfen
  Auth-Gates, Health, autorisierten Wake-Aufruf, Cloud-Wake 501, Cloud-Chat 503
  und App-Token am Upstream. Die bisherige Laufzeit-Assertion wurde durch den
  deterministischen Nachweis ersetzt, dass keine Wartefunktion aufgerufen wird.
- Gemeinsamer Lauf mit
  `PYTHONPYCACHEPREFIX=/tmp/jarvis-pycache .venv/bin/python -m pytest -q tests relay/test_relay.py -o addopts=''`:
  **124 bestanden, 1 Warnung, 1,70 s**. `git diff --check` war fehlerfrei.
- Hardware-Wake, Cloud-Deployment, native App und Bridge-Suite wurden in diesem
  abgegrenzten Arbeitspaket nicht ausgeführt. Die Tests beweisen keinen Betrieb
  auf einem physischen iPhone oder einen bereits laufenden Cloud-Core.
- Umgebungshinweis: Die Suite zeigt eine bestehende urllib3/LibreSSL-Warnung
  (Python 3.9, LibreSSL 2.8.3). Kein Testfehler; für einen späteren Host eine
  unterstützte Python-/OpenSSL-Laufzeit verwenden.

## Offene Voraussetzungen

Ein Cloud-Ziel mit freigegebenem Zugang und ein dauerhaft laufender
Heimnetz-Wake-Knoten sind für dieses Arbeitspaket nicht belegt. Hardware-Wake
am MacBook muss praktisch geprüft werden. Der Fehler mit wiederholten
Sprachberechtigungen, die Stimme und ein interaktiver Sprachmodus sind offen.
Es wurden keine Systemeinstellungen geändert, keine Credentials ausgegeben,
keine Dienste neu gestartet und keine Commits oder Pushes erstellt.
