# Barge-in — gebaut, bitte prüfen statt neu bauen

**Status: umgesetzt von Claude am 2026-09-06, 19:0x Uhr, während Codex bis
20:44 im Ruhemodus war.** Marlon hat das ausdrücklich so entschieden. Diese
Datei war vorher ein Auftrag; sie ist jetzt eine Übergabe. **Nicht noch einmal
implementieren** — durchsehen, verbessern, am Gerät hören.

Scope war `apple/`, sonst nichts. Keine Commits.

## Was der Nutzer wollte

> „außerdem wenn ich rede soll er pausieren und zuhören"
> „er soll aber quasi durchgehend zuhören und wenn ich etwas sage wird er
> unterbrochen"

Also nicht nur Unterbrechen während des Sprechens, sondern ein durchgehend
offenes Mikrofon — auch während „Ich denke nach".

## Geänderte Dateien

| Datei | Änderung |
|---|---|
| `apple/Sources/Services/BargeInDetector.swift` | neu: entscheidet Sprache gegen Rauschen und Echo |
| `apple/Tests/BargeInDetectorTests.swift` | neu: neun Szenarien, eigenständig mit `swiftc` lauffähig |
| `apple/Sources/Services/SpeechController.swift` | Voice Processing, `.voiceChat`, `listenThrough()`, Detektor im Erkennungspfad, `contextualStrings` |
| `apple/Sources/Services/NeuralSpeechPlayer.swift` | `managesAudioSession`, damit der Player die Session abgeben kann |
| `apple/Sources/Stores/AppModel.swift` | `resumeVoice`/`send` halten das Mikrofon offen; `cancelActiveRun` extrahiert |
| `apple/Sources/Views/SettingsView.swift` | Schalter „Durch Sprechen unterbrechen", Feld „Eigene Wörter" |

## Drei Fallen, die beim Bauen auftauchten

Sie standen nicht im ursprünglichen Entwurf und sind der Grund, warum eine
Neuimplementierung wahrscheinlich schlechter würde:

1. **Der Player riss die Aufnahme ab.** `NeuralSpeechPlayer` stellte die
   iOS-Session auf `.playback` und deaktivierte sie danach. Beides beendet die
   Aufnahme. Er gibt die Session jetzt ab, wenn Barge-in aktiv ist.
2. **`send()` blockt bei `isWorking`.** Unterbricht der Nutzer mitten im Lauf,
   wäre seine neue Äußerung kommentarlos verschwunden. `onUtterance` beendet
   den laufenden Turn jetzt still (`cancelActiveRun(announcing: false)`) und
   schickt dann.
3. **Echo in der Satzlücke.** Zwischen Satz N und N+1 ist `isSpeaking` kurz
   `false`, während das Echo von Satz N noch eintrifft. Der Detektor ist
   deshalb für den ganzen offenen Stream zuständig (`isSpeaking ||
   streamIsOpen`) und merkt sich zusätzlich die Wörter des **vorherigen**
   Satzes.

## Bewusste Entscheidungen

- Schlägt `setVoiceProcessingEnabled` fehl, bleibt Barge-in aus statt das
  Mikrofon zu verlieren (`bargeInAvailable`).
- Schwelle: mindestens drei Zeichen **und** zwei aufeinanderfolgende
  Teilergebnisse. Ein Husten stoppt nichts.
- Die Uhr behält Tippen zum Unterbrechen; dort gibt es keine Echokompensation.
- Abschaltbar, Vorgabe an.

## Verifikation (Claude, 2026-09-06)

- `JARVIS-iOS` generic device: **BUILD SUCCEEDED**
- `JARVIS-macOS`: **BUILD SUCCEEDED**
- `BargeInDetectorTests`: bestanden — Auslösung, Blip, Kürze, Echo,
  Interpunktion, Reset, Satzlücke, Leereingaben
- `WatchSentenceQueueTests`, `SpeechSentenceBufferTests`, `AnswerTextTests`:
  bestanden
- Xcode-Projekt mit `xcodegen generate` neu erzeugt (neue Quelldatei)

## Was offen ist — hier hilft Codex wirklich

1. **Nie am Gerät gehört.** Ob die Echokompensation auf diesem Mac und auf dem
   iPhone greift, ist unbewiesen. Das ist die wichtigste offene Frage: greift
   sie nicht, unterbricht JARVIS sich selbst.
2. **Build 10 liegt auf keinem Gerät.** iPhone und Uhr tragen Build 9.
3. **Schwelle am echten Raum kalibrieren.** Drei Zeichen und zwei Updates sind
   begründet, aber nicht gemessen.
4. **Dauerhaft offenes Mikrofon kostet Akku.** Auf dem iPhone noch nicht
   beurteilt.
