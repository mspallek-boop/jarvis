# Messmodus — App-Seite (Auftrag an Codex)

**Status:** Bridge-Seite gebaut von Claude am 2026-09-14 (`bridge/jarvis_bridge.py`,
`bridge/test_timing.py`, `scripts/voice_timing_report.py`). Vertrag:
`docs/BRIDGE_CONTRACT.md` → Abschnitt „Messmodus (2026-09-14)“. Scope dieses
Auftrags ist **nur `apple/`**. Keine Commits.

Hintergrund: `Jarvis Output/Voice-Architektur-Analyse.md`. Wir wollen die
wahrgenommene Latenz `speech_end → playback_started` pro Turn messen, bevor
Endpointing, Streaming und Barge-in umgebaut werden. Ohne diese Zahlen sind alle
Gewinne dort nur Schätzungen.

## Was die App tun soll

1. **Einstellung „Latenz-Debug“** (Standard aus, in `UserDefaults` persistiert —
   Einstellungen müssen das Beenden überleben). Aus = kein zusätzlicher Code-Pfad,
   kein Request.
2. **Monotone Zeitstempel** in Millisekunden erfassen, z. B.
   `Double(DispatchTime.now().uptimeNanoseconds) / 1_000_000`. Nur innerhalb der
   App vergleichbar; nie mit Bridge-Zeiten verrechnen.
3. **Events pro Turn** unter der `client_run_id` sammeln, die `AppModel.send()`
   ohnehin erzeugt (`let id = UUID().uuidString`, `AppModel.swift` ~1428):

| Event | Wo (Stand heute, Zeilen können wandern) | Genau wann |
|---|---|---|
| `speech_end` | `SpeechController`, Transkript-Update (`SpeechController.swift` ~366–372, `lastHeard` ~368) | Zeit des **letzten** Transkript-Wachstums, von dem der Satzende-Timer zählt — beim Abschicken mitgeben, nicht beim Update senden |
| `endpoint_fired` | `completeUtterance()` (~445) | Timer abgelaufen, Äußerung geht an `onUtterance` |
| `request_sent` | `AppModel.send()` direkt vor `client.chatStreaming` (~1443; Watch-Pfad ~1593 ebenso) | |
| `first_text_frame` | `onFrame`-Closure, erster `delta`-Frame dieses Runs (~1450) | einmal pro Run |
| `first_sentence_enqueued` | erster `speech.enqueueSentence` dieses Runs (~1455, ~1490, ~1504) | einmal pro Run |
| `playback_started` | `NeuralSpeechPlayer`, erster geplanter Buffer bei laufender Engine; System-Stimme: `speechSynthesizer(_:didStart:)` | erstes Sample hörbar. Näherung erlaubt (z. B. Planungszeit + `outputNode.presentationLatency`), **Methode im Code-Kommentar nennen** |
| `bargein_detected` | `SpeechController`, wenn `bargeIn.shouldInterrupt` true liefert (~357–365) | |
| `audio_stopped` | nach `stopSpeaking()` / `neuralPlayer.stop()` im Barge-in-Pfad | |

   Die Spracheingabe gehört zum Turn, den sie auslöst: `speech_end` und
   `endpoint_fired` werden gepuffert und der `client_run_id` zugeordnet, sobald
   `send()` sie vergibt.
4. **`/speech` korrelieren:** `JarvisAPIClient.speechRequest(text:)` bekommt
   optional `clientRunID` und `seq` (Index des Satzes im Turn, ab 0) und schreibt
   sie in den JSON-Body (`client_run_id`, `seq`) — **nur** wenn Latenz-Debug an
   ist. `NeuralSpeechPlayer` muss die Run-ID für die Queue kennen
   (`beginQueue`/`enqueue`). Ohne die Felder verhält sich die Bridge exakt wie
   bisher.
5. **Abliefern:** einmal pro Turn `POST /timing` mit
   `{"client_run_id": …, "events": [{"event": …, "t_ms": …, "seq": 0}]}`
   (maximal 64 Events), ausgelöst nach `playback_started` bzw. am Turn-Ende, wenn
   nichts gesprochen wurde; ein Barge-in darf ein zweites Paket nachschicken.
   Detached, niedrige Priorität, Fehler still ignorieren, **nie** Wiedergabe oder
   Mikrofon blockieren. Antwort `enabled: false` heißt: Bridge-Flag ist aus —
   nichts weiter tun.
6. **Nie Text** in Events oder Zusatzfeldern.

## Tests und Nachweis

- Swift-Unit-Test für den Event-Sammler: Reihenfolge, einmal pro Run,
  Zuordnung von `speech_end`/`endpoint_fired` zum folgenden Run, JSON-Payload
  entspricht dem Vertrag, keine Texte enthalten, ≤ 64 Events.
- `xcodebuild` für `JARVIS-macOS` und `JARVIS-iOS` (Befehle in `CLAUDE.md`).
- Zum Installieren mit Zertifikat bauen, installieren und danach selbst prüfen —
  „installiert“ erst nach Kontrolle.
- End-to-End (mit Marlon): `touch ~/.hermes/voice-timing-on`, Latenz-Debug an,
  10 Sprach-Turns, dann
  `.venv/bin/python scripts/voice_timing_report.py` → `perceived_latency` hat
  n ≥ 10, und `--run <id>` zeigt für einen Turn App- und Bridge-Zeitleiste.
