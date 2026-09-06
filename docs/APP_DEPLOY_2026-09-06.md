# JARVIS 0.3.0 / Build 8 — Deployment vom 2026-09-06

## Tatsächlich installiert

- Mac: `/Applications/JARVIS.app`, Bundle-Version **8** geprüft, signiert mit
  unveränderter Development-Identität und Mikrofon-Entitlement. `open` erfolgreich;
  UI-Prüfung von Computersteuerung abgewiesen, weil der Mac gesperrt ist.
- iPhone: `devicectl` bestätigt erfolgreiche Installation von
  `at.marlon.jarvis.ios`. Startversuch explizit wegen gesperrtem Gerät abgewiesen
  (`FBSOpenApplicationErrorDomain 7`). Die Installation selbst war erfolgreich.
- Watch: Direkte `devicectl`-Installation von
  `at.marlon.jarvis.ios.watchkitapp` erfolgreich. Anschließender direkter Start
  von `devicectl` ebenfalls erfolgreich bestätigt. Der Build enthält die bereits
  vorhandene `JARVIS-WatchComplication.appex`, Bundle
  `at.marlon.jarvis.ios.watchkitapp.launcher`, ebenfalls Version 8.

Kein End-to-End-Voice-Test auf gesperrten Geräten behauptet. Die Watch spricht
weiterhin mit der Apple-Systemstimme und benötigt den vorhandenen iPhone-Pfad.

Mac-Rollback vor dem Update gesichert:
`/var/folders/b1/6tcm65v53w1dqs2l4q68rns80000gn/T/jarvis-build7-backup-mv7ju7_4/JARVIS.app`.

## Vorbereitet, aber noch nicht aktiviert

- `voice/server.py`: lokale neuronale Aiden-Stimme; echter temporärer
  HTTP-/Modelltest erfolgreich, kein dauerhafter Worker aktiv.
- `bridge/jarvis_bridge.py`: `/speech` und `/activity`; Erweiterungen getestet,
  noch nicht nach `~/.hermes/services/` kopiert.
- `launchd/com.jarvis.availability.plist`: `caffeinate -s` für Erreichbarkeit bei
  dunklem Bildschirm am Netzteil. Kein Versprechen für echten Ruhezustand.
- Worker-LaunchAgent vorbereitet unter `/tmp/com.jarvis.neural-voice.plist`,
  ohne Credentials. Er liest den App-Token erst im Worker aus der vorhandenen
  Hermes-Umgebung. Laufzeit nutzt ausschließlich das heruntergeladene Modell.

Der gebündelte Befehl zum Kopieren und Aktivieren wurde **vor Ausführung** von
der automatischen Freigabeprüfung zurückgewiesen: dauerhafte LaunchAgents und
Wachhalten seien durch die frühere Vorgabe „keine Systemeinstellungen“ nicht
hinreichend autorisiert. Eine ausdrückliche Freigabe ist angefragt und noch
nicht eingegangen. Keine Umgehung oder Aktivierung über einen anderen Weg.

Bis zur Aktivierung nutzt Build 8 bei fehlendem Speech-Worker seine
Systemstimme; bei fehlendem Activity-Endpunkt bleibt die allgemeine
Arbeitsanzeige. Bereits vorhandener Chat bleibt kompatibel.

## Änderungen dieser Ausbaustufe

- Sprache: `voice/{server.py,test_server.py,benchmark.py,download_model.py,requirements-lock.txt,README.md}`,
  `bridge/test_speech.py`, `apple/Sources/Services/{NeuralSpeechPlayer,SpeechText,SpeechController,JarvisAPIClient}.swift`,
  Sprachoption in `apple/Sources/Views/SettingsView.swift`, Buildnummer in `apple/project.yml`.
- Rechercheoberfläche: `bridge/jarvis_bridge.py`, `bridge/test_activity.py`,
  `apple/Sources/Services/AnswerText.swift`, `apple/Sources/Stores/AppModel.swift`,
  `apple/Sources/Views/{ContentView,MessageBubble}.swift`.
- Swift-Prüfungen: `apple/Tests/{SpeechTextTests,AnswerTextTests}.swift`.
- Netzteil-Verfügbarkeit: `launchd/com.jarvis.availability.plist` vorbereitet.
- Dokumentation: `docs/{ALLTAGSHELFER_2026-09-06,APP_DEPLOY_2026-09-06,TARGET_ARCHITECTURE,BRIDGE_CONTRACT}.md`.

Generierte Xcode-Projektdateien und Plists sind aktualisiert. Bestehende
Änderungen, insbesondere Watch-Komplikation und frühere Bridge-Korrekturen,
sind erhalten. Keine Commits, Pushes, Resets oder Cloud-Ressourcen.

## Prüfungen

- Exakt gewünschte Python-Hauptsuite: **110 bestanden**, bestehende
  LibreSSL/urllib3-Warnung.
- Hauptsuite + Relay + Voice + socketfreie Bridge-Erweiterungen:
  **156 bestanden**.
- Gesamte Bridge: **52 bestanden**, lokale HTTP-Testserver außerhalb der Sandbox.
- Swift: **8** Sprachsegmentierungs- und **6** Quellenformatierungsfälle bestanden.
- macOS- und iOS-Scheme samt Watch: **BUILD SUCCEEDED**.
- Codesign/Watch-Einbettungsprüfung bestanden; Mac-Mikrofon-Entitlement erhalten.
- Öffentliche Recherche über echte Bridge/Hermes: **14,19 s**, Werkzeug
  `web_extract`, Antwort mit korrektem Referenzlink.
- Qwen/Aiden: echter temporärer HTTP-Worker-Test mit 14 Audioframes, sauberem
  Abschluss und Auth-Abweisung ohne Token; 2,601 s bis erstes Audio inklusive
  kaltem Modell, 4,802 s Gesamtgenerierung für 6,32 s Audio.
- `git diff --check` erfolgreich.

Buchungsintegrationen, Kontoverbindungen und native Freigabekarten sind offen.
Details und Vergleich mit dem Referenzprojekt: `ALLTAGSHELFER_2026-09-06.md`.
