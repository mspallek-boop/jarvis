# JARVIS als Alltagshelfer — überprüfter Stand 2026-09-06

Autoritatives Repo: `/Users/marlon/Documents/JARVIS`, Branch
`checkpoint/bridge-port-8770`. Bestehende Änderungen bleiben erhalten. Die
Cloud-Planung ist auf Wunsch des Nutzers beendet.

## Abgleich mit dem gewünschten Vorbild

Quelle: [eadmin2/jarvis_ai](https://github.com/eadmin2/jarvis_ai).
Das Vorbild verbindet Sprache und HUD mit Hermes. Sein README beschreibt
Werkzeugaktivität, Unterbrechen, Freigabekarten, Medienpanels und persistente
Sitzungen. Es belegt keine fertige Integration für Uber oder Restaurantbuchungen.
Die native App bleibt die Oberfläche des bestehenden Hermes; ein zweiter Agent
oder ein Austausch des autoritativen Repos ist dafür nicht erforderlich.

| Fähigkeit | Nachweis bzw. Lücke |
|---|---|
| Recherchieren | Echter Bridge→Hermes-Test: `web_extract` las das Referenzrepo in 14,19 s; Antwort enthielt überprüfte Funktionen und Quellen-URL. |
| Websuche und Browser bedienen | Laufendes Hermes meldet `web` und `browser` aktiviert und konfiguriert. Das ist eine Werkzeug-Inventur, kein erfolgreicher Test jeder Website. |
| Gedächtnis | `memory` und `session_search` aktiviert und konfiguriert. Bridge bewahrt Sitzungszuordnungen und verwendet einen festen Memory-Scope. Das bedeutet **nicht**, dass jede Information dauerhaft gespeichert oder jederzeit vollständig erinnert wird. |
| Sprache zuerst | App startet im Sprachmodus, dezente untere Linie öffnet Tippen; vorhandene Berechtigungs- und Abbruchkorrekturen bleiben erhalten. |
| Natürlichere Stimme | Lokales Qwen3-TTS/Aiden vorbereitet und mit echtem Audio getestet. Mac und iPhone besitzen Streaming-Player; dauerhafter Dienst benötigt noch die angefragte Freigabe. Watch verwendet weiterhin ihre Systemstimme. |
| Sichtbare Arbeit | Neu: authentifizierter `/activity`-Endpunkt und Anzeige des tatsächlichen Hermes-Arbeitsschritts in Voice und Chat. Kein fingierter Fortschrittsbalken. |
| Recherchequellen öffnen | Neu: Markdown- und einfache HTTP(S)-Links sind im Voice-Ergebnis und Verlauf anklickbar. Andere URL-Schemata werden nicht aktiviert. |
| Tisch reservieren | Recherche ist vorhanden. Anbieter-Login, Verfügbarkeitsprüfung, verbindlicher Abschluss, Bestätigung und Wiederholschutz sind noch nicht Ende-zu-Ende integriert. Keine Reservierung wurde ausgelöst. |
| Uber buchen | Noch keine Kontoverbindung oder Buchungsintegration. Die Riders API erfordert laut Uber Zugang/Freigabe. Eine Deeplink-Übergabe kann den Buchungsablauf in Uber vorbereiten, wäre aber keine bereits gebuchte Fahrt. |
| Aktionsfreigaben | Hermes bietet Approval-Ereignisse; die native Bridge/App reicht sie noch nicht als bedienbare Freigabekarten durch. Eine laufende Freigabe darf nicht automatisch bestätigt werden. |
| Medienpanels und Antwort während der Generierung | Noch keine native Umsetzung des HUD-Plugins. Sprach-Audio streamt, aber `/chat` sammelt die Hermes-Textantwort bis zum Ende. Sprachliches Barge-in ist noch kein nachgewiesenes Feature; Unterbrechen per Tippen ist vorhanden. |

## Sinnvolle nächste abgegrenzte Ausbaustufe

Native Freigabekarten für **exakt eine** angefragte Aktion: Zusammenfassung,
Anbieter, Termin/Ziel, Personenzahl bzw. Abholort, Preis/Stornobedingungen soweit
verfügbar, dann Bestätigen oder Ablehnen. Die Bridge muss die Entscheidung an
`client_run_id`, Hermes-Run und exakte Approval-Request-ID binden. Keine
pauschalen Sitzungs- oder Dauerfreigaben. Abgelaufene/ersetzte Karten ablehnen,
Wiederholungen dürfen keinen zweiten Kauf auslösen. Erfolg nur mit echter
Anbieterbestätigung anzeigen; bei unklarem Ergebnis zuerst Status nachsehen.

Eine Hermes-Kommando-Freigabe allein sichert noch nicht automatisch jede
Browserbuchung ab. Für die erste echte Reservierung muss der konkrete
Buchungsablauf inklusive Abschlusskontrolle getestet werden. Dafür zunächst
einen vom Nutzer gewünschten Anbieter wählen und das Konto verbinden.

Für Uber zunächst eine überprüfbare Übergabe von Abholort und Ziel an die
Uber-App anbieten. Direkte Buchung erst nach bestätigtem API-Zugang und OAuth;
keine Zugangsdaten in App-Quelltext oder Relay.

[Uber Riders: Zugang](https://developer.uber.com/docs/riders/introduction),
[Uber Deeplinks](https://developer.uber.com/docs/riders/ride-requests/tutorials/deep-links/introduction).

## Erreichbarkeit ohne Cloud

Im **echten Systemruhezustand** führt der Mac Hermes nicht aus. Ein dunkler
Bildschirm kann dagegen mit laufendem System kombiniert werden.
`launchd/com.jarvis.availability.plist` ist dafür vorbereitet: `caffeinate -s`
verhindert Systemschlaf nur am Netzteil, ohne den Bildschirm wachzuhalten.
Quelle: lokal geprüfte macOS-Manpage `caffeinate(8)`.

Dies ist keine Garantie für geschlossenen Deckel, manuell ausgelösten Schlaf,
Neustart vor Benutzeranmeldung, Stromausfall oder unterbrochenes Tailscale.
Der Dienst ist ein Benutzer-LaunchAgent und startet erst nach Anmeldung.
Erhöhten Stromverbrauch und Wärme gegenüber echtem Schlaf berücksichtigen.

Die automatische Freigabeprüfung hat das dauerhafte Aktivieren dieses Dienstes
und der lokalen Stimme samt gebündeltem Bridge-Neustart wegen der früheren
Vorgabe „keine Systemeinstellungen“ abgewiesen. Es wurde nichts aus diesem
abgewiesenen Befehl ausgeführt. Eine ausdrückliche Freigabe wurde angefragt.

## Prüfungen dieser Ausbaustufe

- Gewünschter Lauf `PYTHONPYCACHEPREFIX=/tmp/jarvis-pycache .venv/bin/python -m pytest -q`:
  **110 bestanden**, eine bestehende LibreSSL/urllib3-Warnung.
- Hauptsuite + Relay + Voice + socketfreie neue Bridge-Tests: **156 bestanden**.
- Gesamte Bridge-Suite mit lokalen HTTP-Testservern: **52 bestanden**.
- Swift: **8** Textsegmentierungsfälle und **6** Quellenformatierungsfälle.
- Native Mac- und iOS-Builds einschließlich Watch: Build erfolgreich; endgültige
  Installations- und Aktivierungsstände siehe nachfolgenden Deployment-Bericht.
- Signaturen, Mac-Mikrofon-Entitlement und ausführbare Watch-Einbettung geprüft.
- Echter Recherchetest auf öffentlicher Quelle bestanden. Keine Buchung,
  Bezahlung oder Nachricht an Dritte ausgelöst.
