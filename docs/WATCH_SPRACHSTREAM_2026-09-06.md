# Satzweise Sprachausgabe — Build 10

Codex hat diese Änderung um 17:31–17:39 begonnen und ohne Bericht stehen
gelassen. Dieser Bericht schließt sie ab: geprüft, nicht neu gebaut.

## Was sich ändert

Die Sprachausgabe wartete bisher auf das Ende der gesamten Hermes-Antwort.
Jetzt wird jeder abgeschlossene Satz sofort gesprochen — auf Mac, iPhone und
Uhr. Bei langen Antworten verschwindet damit die Wartezeit vor dem ersten Wort.

## Geänderte Dateien

| Datei | Rolle |
|---|---|
| `apple/Sources/Services/SpeechSentenceBuffer.swift` | neu: schneidet den Delta-Strom an Satzgrenzen |
| `apple/Sources/Services/SpeechController.swift` | `beginStream` / `enqueueSentence` / `endStream`, Warteschlange gesprochener Sätze |
| `apple/Sources/Services/WatchConnectivityController.swift` | neu: `deliverSentence`, sendet je Satz mit laufender Nummer ans Watch-Gerät |
| `apple/WatchApp/WatchSentenceQueue.swift` | neu: ordnet, entdoppelt und begrenzt die empfangenen Sätze |
| `apple/WatchApp/WatchConnectivityClient.swift` | empfängt Einzelsätze, spricht in Reihenfolge, holt Lücken aus der Endliste |
| `apple/Sources/Stores/AppModel.swift` | verdrahtet beide Wege (`send`, `sendFromWatch`) |
| `apple/Sources/Views/ContentView.swift`, `JarvisAPIClient.swift` | Anpassungen an die Stream-API |
| `apple/Tests/SpeechSentenceBufferTests.swift`, `WatchSentenceQueueTests.swift` | neu |
| `apple/project.yml` | gemeinsame Buildnummer 10; Xcode-Projekt daraus regeneriert (17:39) |
| `apple/README.md` | Abschnitt „Die Uhr spricht satzweise mit (Build 10)“ (von Claude ergänzt) |

## Korrektheit der Randfälle

Geprüft am Quelltext, nicht nur an den Tests:

- **Reihenfolge:** Jeder Satz trägt eine Sequenznummer. `WatchSentenceQueue`
  hält verfrühte Sätze zurück, bis die Lücke geschlossen ist.
- **Doppelung:** Ein bereits gesprochener Index wird verworfen, auch wenn er in
  der abschließenden Satzliste erneut auftaucht.
- **Lücke:** Der Abschluss-Funkspruch trägt die vollständige Liste; fehlende
  Sätze werden daraus nachgeholt.
- **Uhr nicht erreichbar:** `deliveredCount == 0` löst die alte Komplettausgabe
  aus. Kein stiller Ausfall.
- **Endfassung weicht ab:** Ersetzt Hermes den gestreamten Wortlaut, bleibt der
  maßgebliche Text sichtbar, wird aber nicht erneut vorgelesen.
- **Streamzustand bei Fehler:** `stopSpeaking()` setzt `streamIsOpen` zurück und
  leert die Warteschlange. Sowohl der Fehlerpfad als auch der Pfad ohne
  Sprachausgabe schließen den Stream — kein hängender Stream für die nächste
  Antwort.
- **Grenzen:** höchstens 1000 Sätze je Anfrage, höchstens 600 Zeichen je Satz.

## Verifikation

Alles am 2026-09-06 nach Codex' Ruhemodus ausgeführt:

| Prüfung | Ergebnis |
|---|---|
| `JARVIS-iOS` (generic/platform=iOS, inkl. Watch + WidgetKit) | **BUILD SUCCEEDED** |
| `JARVIS-macOS` (platform=macOS) | **BUILD SUCCEEDED** |
| `WatchSentenceQueueTests` | bestanden (Reihenfolge, Entdoppelung, Nachholen, Grenzen) |
| `SpeechSentenceBufferTests` | bestanden (7 Szenarien) |
| `SpeechTextTests` | bestanden (8 Fälle) |
| `AnswerTextTests` | bestanden (6 Fälle) |
| `pytest -q` (Repositoriumswurzel) | 110 bestanden, 0 fehlgeschlagen |
| `pytest -q bridge/ relay/` | 75 bestanden |
| `git diff --check` | fehlerfrei |
| Buildnummer in beiden Bundles | 10, Watch-App unter `JARVIS.app/Watch/JARVIS-Watch.app` |
| Alle vier Komplikationskennungen | im gebauten `.appex` vorhanden |

Die Builds liefen mit `CODE_SIGNING_ALLOWED=NO`. `apple/scripts/verify_app_bundle.py`
wurde deshalb nicht ausgeführt; es setzt eine echte Entwicklersignatur voraus.

## Offen

1. **Build 10 ist auf keinem Gerät.** iPhone und Uhr tragen noch Build 9. Für
   die Installation braucht es einen signierten Build und entsperrte Geräte.
2. **Sprechprobe auf der Uhr fehlt.** Dass satzweise vorgelesen wird, ist nur
   am Quelltext und an den Einheitentests belegt, nicht am Gerät gehört.
3. **Komplikationsauswahl aus Build 9 weiterhin ungeprüft** — der Watch-Start
   scheiterte damals am gesperrten Gerät (`FBSOpenApplicationErrorDomain 7`).

Keine Commits, keine Pushes, keine Änderungen am Backend.
