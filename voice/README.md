# Lokale natürliche Stimme

`server.py` erzeugt deutsche Sprache mit Qwen3-TTS, Stimme Aiden, auf dem Mac.
Es ersetzt keine Hermes-Inferenz. Text geht per authentifiziertem `/speech`
über die Bridge an den ausschließlich auf `127.0.0.1:8788` gebundenen Worker.
Der Worker liest nur `JARVIS_APP_TOKEN`; der Hermes-API-Key wird nicht benötigt.

Abhängigkeiten: `requirements-lock.txt`, separate Python-3.11-Umgebung unter
`LocalData/Runtime/voice-venv`. Das gepinnte Modell wird einmalig durch
`download_model.py` geladen; `jarvis-source.json` im Modelldirectory hält die
Revision fest. Laufzeit verwendet `HF_HUB_OFFLINE=1`, deaktivierte Telemetrie
und keine impliziten Hugging-Face-Tokens. Modell und Proben sind gitignoriert.

Start (im Repo, keine Zugangsdaten in Argumenten):

```sh
LocalData/Runtime/voice-venv/bin/python voice/server.py \
  --model LocalData/Runtime/voice-models/qwen3-0.6b-custom-4bit
```

Prozess hat einen Auftrag gleichzeitig; bei Überlast HTTP 429. Text maximal
600 Unicode-Codepoints pro Request, Audio maximal 60 Sekunden. NDJSON liefert
PCM16 LE / 24 kHz und einen Abschlussframe. Fehlerantworten enthalten keinen
Eingabetext oder interne Fehlermeldungen. Der native Player startet während
des Empfangs; längere Antworten werden in kleinere Textstücke geteilt.

Gemessene feste deutsche Probe auf diesem M3-Mac: warmer Modellaufruf mit
Aiden 0,261 s bis zum ersten Chunk, 2,688 s Generierung für 6,32 s Audio.
Echter HTTP-Worker-Test mit kaltem Modell: 2,601 s bis zum ersten Audio,
4,802 s bis Abschluss. Modellspitze ca. 2,2 GB; keine Zusage gleicher Werte
bei längeren Texten oder gleichzeitiger Hermes-/Browserlast.

Mac/iPhone fallen vor dem ersten Audio bei Dienstfehlern auf ihre Systemstimme
zurück. Nach begonnener fehlerhafter Wiedergabe bleibt die Textantwort lesbar.
Die Watch benutzt vorerst ihre eigene Systemstimme. Natürlichkeit und Akzent
sind anhand der Probe subjektiv abzunehmen; Aiden ist keine deutsche
Sprecheraufnahme und keine Stimmkopie.

Dauerhafter Start ist separat freizugeben. Der vorhandene
`launchd/com.jarvis.voice.plist` gehört zum alten Web-Sprachserver; ihn nicht
für diesen Worker überschreiben. Neuer Dienstname: `com.jarvis.neural-voice`.

Tests: `voice/test_server.py` läuft ohne Modell, Netzwerk oder Audiohardware;
`benchmark.py` ist ein ausdrücklich separater Hardware-Benchmark.
