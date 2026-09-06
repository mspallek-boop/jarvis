# JARVIS 0.3.0 (Build 7): App-Update vom 2026-09-05

## Installationsstand

| Ziel | Ergebnis |
|---|---|
| Mac | Signiert unter `/Applications/JARVIS.app` installiert und gestartet. UI meldet Hermes online. Echte Chat-Antwort aus der App erhalten; nach Entitlement-Korrektur auch eine reale Sprachaufnahme mit anschließender Hermes-Anfrage beobachtet. |
| iPhone 14 Pro Max | Signierter Build fertig und geprüft. Installation von iOS abgewiesen: `No space left on device`, CoreDevice 3002 / POSIX 28. Bestehende App nicht gelöscht. |
| Apple Watch Series 7 | Signierter Build mit ausführbarem Companion fertig und geprüft. Direkte Installation abgewiesen: Developer Mode disabled, CoreDevice 10005. |
| Bridge | Ausgerollte Datei in `~/.hermes/services/` stimmt bytegenau mit `bridge/jarvis_bridge.py` überein. Kein unnötiger Neustart. |
| Cloud | Kein Account/Host vorhanden, daher kein Cloud-Deployment. Kostenrahmen des Nutzers: kostenlos. |

Der signierte iPhone-Build enthält `Watch/JARVIS-Watch.app`. Zusätzlich wurde
versucht, die Watch-App direkt zu installieren. Xcodes fehlende watchOS-26.5-
Komponente wurde über `xcodebuild -downloadPlatform watchOS` installiert.

## App-Änderungen

- Voice startet auf Mac/iPhone beim Öffnen mit vorhandenem Token und erteilter
  Berechtigung. Eine Pause von 1,6 Sekunden nach der letzten Transkriptänderung
  schließt einen gesprochenen Satz ab und sendet ihn. Nach einer gesprochenen
  Antwort wird wieder zugehört. Während der Ausgabe bleibt das Mikrofon aus.
- Unten öffnet eine dezente 48 × 3-Punkte-Linie die Texteingabe. Die unsichtbare
  Trefferfläche bleibt 44 Punkte hoch und besitzt eine Accessibility-Beschriftung.
  Texteingabe und Hintergrundwechsel pausieren Audio.
- Tippen auf den Orb unterbricht eine Sprachantwort. Bei einer laufenden
  Hermes-Anfrage wird `/stop` mit derselben `client_run_id` aufgerufen.
- Standard-URL und Migration verwenden den verifizierten privaten Endpunkt
  `https://macbook-air-von-marlon.tailfb3c35.ts.net:8443`.
- Alte Eloquence-Stimmen werden nicht mehr als natürliche deutsche Stimmen
  angeboten. Geladene hochwertige deutsche Stimmen werden vor Basisstimmen
  gewählt und vor der nächsten Ausgabe neu erkannt.
- Watch startet die Spracheingabe beim Öffnen, liest die Antwort vor und
  beendet einen ausbleibenden Antwortversuch mit einem begrenzten Timeout.
  Die Kommunikation läuft weiterhin über das erreichbare iPhone.

## Ursache der Mac-Berechtigungsprobleme

Die bisher installierte App hatte eine Ad-hoc-Signatur. Der neue Build nutzt
Apple Development und dieselbe feste Bundle-ID. Berechtigungsanfragen sind
prozessweit zusammengeführt: keine erneute automatische Abfrage nach Ablehnung.

Beim Regenerieren stellte sich zusätzlich heraus, dass XcodeGen das bisher nur
in der Entitlements-Datei vorhandene Mikrofon-Entitlement löschte. TCC meldete
explizit das fehlende `com.apple.security.device.audio-input`. Es steht jetzt
unter `entitlements.properties` in `apple/project.yml`; der installierte,
signierte Build wurde darauf geprüft. Systemeinstellungen wurden nicht durch
den Agenten geändert. Nach der Korrektur wurde echte Spracheingabe beobachtet.

## Verifikation

- macOS-Scheme: `BUILD SUCCEEDED` mit echter Development-Signatur.
- iOS-Scheme einschließlich Watch: `BUILD SUCCEEDED` mit echten Signaturen.
- `apple/scripts/verify_app_bundle.py`: Mac-Identität, Mikrofon-Entitlement und
  Datenschutzhinweise geprüft; iOS-/Watch-Signaturen, Bundle-IDs, Watch-Einbettung,
  ausführbare Watch-Datei und identische Versionsnummern geprüft.
- Bridge-Suite: **40 bestanden**. Der erste Sandbox-Lauf konnte den temporären
  HTTP-Testserver nicht binden; derselbe Lauf außerhalb der Sandbox bestand.
- Hauptsuite/Relay: siehe abschließendes Testergebnis dieses Tasks.
- `git diff --check`: fehlerfrei.
- Mac-UI: Voice-Startansicht, Öffnen der Texteingabe über die Linie und echte
  Antwort `JARVIS APP TEST OK.` verifiziert. Reale Sprachaufnahme nach finaler
  Installation beobachtet. Kein vollständiger wiederholter Voice-Dauertest;
  keine erfolgreiche Geräteinstallation auf iPhone/Watch behauptet.

Build-Warnungen: AppIntents-Metadaten ohne AppIntents-Abhängigkeit übersprungen;
iOS-Orientierungshinweis für iPad. Kein Buildfehler.

## Fertige Artefakte und Wiederaufnahme

- Mac: `/tmp/jarvis-release-macos/Build/Products/Debug/JARVIS.app`
- iPhone inklusive Watch: `/tmp/jarvis-release-ios/Build/Products/Debug-iphoneos/JARVIS.app`
- Watch direkt: `/tmp/jarvis-release-ios/Build/Products/Debug-watchos/JARVIS-Watch.app`
- Ursprüngliches Mac-App-Backup (Build 6):
  `/var/folders/b1/6tcm65v53w1dqs2l4q68rns80000gn/T/jarvis-app-rollback-wmylnjg1/JARVIS.app`

Nach Freigabe von iPhone-Speicher und Aktivierung des Watch-Entwicklermodus:
Installationen über `devicectl` wiederholen, installierte Bundle-Versionen
abfragen und beide Apps auf den echten Geräten starten. Keine App-Deinstallation
als Workaround; lokale Gespräche und Schlüsselbund erhalten.

## Stimme: Qualitätsziel weiterhin offen

Auf dem Mac waren nur Anna kompakt und Eloquence-Stimmen installiert, alle
Qualitätsstufe 1. Ein besserer Pitch oder ein anderer Name erzeugt daraus keine
hochwertige Stimme. Die Eloquence-Vorauswahl ist korrigiert, eine natürliche
Stimme aber noch nicht praktisch abgenommen.

Kostenloser nächster Schritt: eine hochwertige deutsche Apple-Stimme laden.
JARVIS erkennt sie automatisch. Apple beschreibt den Download unter
[Systemstimme ändern](https://support.apple.com/de-ch/guide/mac-help/mchlp2290/mac).
Alternative: externer TTS-Dienst nach Auswahl des Nutzers; im geprüften
Hermes-Environment sind weder ElevenLabs- noch OpenAI-TTS-Keys konfiguriert.
Keine Credentials ins Handy eingebaut, kein neuer TTS-Dienst aktiviert.

## Kostenlose Cloud

Oracle stellt Always-Free-VMs bereit, kann ungenutzte Instanzen aber zurückfordern;
Account und verfügbare Kapazität sind Voraussetzung. Ein kostenloser Server
macht Modellnutzung nicht automatisch kostenlos.
[Oracle Always Free](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm).
Render Free schläft nach 15 Minuten ohne eingehende Requests ein und hat
flüchtigen lokalen Speicher; das passt schlecht zum direkten Voice-Start mit
persistenten Gesprächen. [Render Free](https://render.com/docs/free).

Die Cloud-Core-/Mac-Tools-/Heimnetz-Wake-Aufteilung bleibt im
`PHASE2_BEWERTUNG.md` beschrieben. Es wurde nichts Kostenpflichtiges bestellt.

Alle vorhandenen Änderungen bleiben erhalten. Kein Reset, Commit, Push,
`sudo`, Zugriff auf den Alt-Prototyp oder Löschen von Nutzerdaten.
