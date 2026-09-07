# Full Setup Guide

Tested on macOS (Apple Silicon) with Hermes Agent v0.16. Allow ~1 hour.

## 1. Hermes Agent (the brain)

Install Hermes Agent and give it an LLM provider — follow the
[official quickstart](https://hermes-agent.nousresearch.com/docs/getting-started/quickstart).
Verify `hermes` works in your terminal before continuing.

Enable its API server in `~/.hermes/.env`:

```bash
API_SERVER_ENABLED=true
API_SERVER_KEY=<long random secret>      # required — full toolset incl. terminal!
```

Start the gateway (`hermes gateway`) and verify:

```bash
KEY=$(grep '^API_SERVER_KEY=' ~/.hermes/.env | cut -d= -f2)
curl -H "Authorization: Bearer $KEY" http://127.0.0.1:8642/health
# {"status": "ok", ...}
```

Recommended: add voice-behavior rules to your global `~/.hermes/SOUL.md`
(short spoken sentences, no markdown aloud, never speak secrets, announce risky
actions and wait for approval). The agent — not the voice server — should own
its personality. A ready-made J.A.R.V.I.S. persona ships in
[`hermes-plugin/SOUL.jarvis.md`](../hermes-plugin/SOUL.jarvis.md):

```bash
cat hermes-plugin/SOUL.jarvis.md >> ~/.hermes/SOUL.md
```

## 2. ElevenLabs (the voice) — optional

Create an API key at elevenlabs.io and pick a voice from their library, noting
its `voice_id`. Add to `~/.hermes/.env`:

```bash
ELEVENLABS_API_KEY=...
```

Then set the real `voice_id` under `voice:` in `config/server.yaml` — the
shipped value is the placeholder `YOUR_ELEVENLABS_VOICE_ID` and will fail.

For the HUD's quota bar, give the key the **User → Read** permission.

**Without an ElevenLabs key**, `voice.fallback: macos` (the default) makes the
server speak through the built-in macOS `say` command instead: offline, free,
no account. It yields the same 16 kHz mono PCM framing, so the HUD, barge-in
and the phone client behave identically — only the voice differs. Set
`voice.macos_voice` to any installed system voice (e.g. `Daniel`) or leave it
empty for the system default. Set `fallback: ""` to restore the old behaviour
of failing the turn when no key is present.

## 3. The voice pipeline server (this repo)

```bash
cd server
python3 -m venv .venv
# CPU-only torch/torchaudio first — see README's "Install" section for why
# (plain `pip install torch` pulls several GB of unused CUDA packages).
.venv/bin/pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu
.venv/bin/pip install fastapi uvicorn requests pyyaml numpy anthropic \
    RealtimeSTT faster-whisper silero-vad websockets psutil
cp config/server.example.yaml config/server.yaml
```

On macOS, `RealtimeSTT` pulls in PyAudio, which needs the portaudio C library
present *before* pip runs or the wheel build fails:

```bash
brew install portaudio
```

Use Python 3.11 or newer for this venv — 3.9 is too old for current torch
wheels.

Note: `faster-whisper` and `silero-vad` are REQUIRED — recent RealtimeSTT
releases treat them as optional extras and fail at runtime without them
(silently for VAD, loudly for the engine). The first start takes 60–90 s
(torch import + model download); subsequent starts are faster.

Edit `config/server.yaml`: set `voice.voice_id`, and adjust the `machines:`
list (or delete it). The first run downloads the Whisper model (~460 MB for
`small.en`).

### TLS certificates (required for browser microphone)

Browsers only expose the mic to secure origins:

```bash
scripts/make-certs.sh            # auto-detects your LAN IP for the SAN
```

Trust `certs/cert.pem` on each device (macOS: Keychain; Windows:
`certutil -user -addstore Root cert.pem`; iPhone: download
`https://host:8765/hud/jarvis.cer`, install profile, then enable in
Settings → General → About → Certificate Trust Settings).

Optional but nice: rename your host's mDNS name (`sudo scutil --set
LocalHostName jarvis` on macOS) so the HUD lives at `https://jarvis.local/hud/`.
Port 443 needs the wildcard bind already set in the example config.

### HUD access token

```bash
echo "JARVIS_HUD_TOKEN=jarvis-$(python3 -c 'import secrets;print(secrets.token_hex(3))')" >> ~/.hermes/.env
```

The HUD asks for this once per device. Omit the variable entirely to disable
auth (not recommended).

### Boot greeting (one-time, ~110 ElevenLabs characters)

```bash
scripts/make-boot-audio.sh YourFirstName
```

### Run it

```bash
.venv/bin/python server.py
```

Wait ~40 s for the STT model to warm, then open `https://YOUR_HOST/hud/`.
Run `scripts/jarvis-health.sh` to check all five services.

## 4. Auto-start on boot (macOS)

Copy the two plists from `launchd/`, edit the `/PATH/TO` and `YOUR_USER`
placeholders, then:

```bash
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.jarvis.voice.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.jarvis.dashboard.plist
```

**Read the comments in the plists** — there are two macOS traps (external-drive
TCC permissions and log-path location) that produce silent hangs or `EX_CONFIG`
errors if ignored. Day-to-day management: `scripts/jarvis-{start,stop,restart,health}.sh`.

## 5. Optional extras

**Push-to-talk client** (Windows/Linux box with a mic):

```bash
cd client
python -m venv .venv && .venv/Scripts/pip install sounddevice websockets numpy openwakeword
python client.py --push-to-talk --server ws://YOUR_HOST:8765/ws --list-devices
```

**GPU worker stats** (shows in the Machines panel): copy
`worker/worker_stats.py` to the worker machine, `pip install psutil`, run it,
and point a `machines:` entry's `stats_url` at `http://worker-ip:8767/stats`.

**GPU speech recognition** — the single biggest quality upgrade if you own any
NVIDIA machine on the LAN. On that machine:

```
cd worker
python -m venv .venv
.venv/Scripts/pip install faster-whisper fastapi uvicorn nvidia-cublas-cu12 nvidia-cudnn-cu12
copy run-stt.example.bat run-stt.bat    # fill in your JARVIS_HUD_TOKEN value
run-stt.bat
```

Then uncomment the `stt.remote:` block in the server's `server.yaml` (point
`url` at the GPU machine) and restart the voice server. Result: `large-v3-turbo`
accuracy at ~0.2 s per utterance, with automatic fallback to the local model
whenever the GPU machine is off. For auto-start at Windows logon, drop a
`JarvisSTT.vbs` in `shell:startup` (template in the .bat comments).

**Phone app feel**: open the HUD in Safari/Chrome on your phone →
Share → Add to Home Screen.

**Let the agent put things on your screen** (the showstopper): install the
bundled Hermes plugin so "show me a video of X on screen" makes holographic
media panels materialize on every open HUD:

```bash
cp -R hermes-plugin/hud_display ~/.hermes/plugins/hud_display
# edit ~/.hermes/plugins/hud_display/schemas.py: replace YOUR_HOST
hermes plugins enable hud_display     # repeat with -p <profile> if you use profiles
# restart your hermes gateway
```

The plugin needs `JARVIS_HUD_TOKEN` in `~/.hermes/.env` (same token as the
HUD). Directory name must stay a valid Python module name — hyphens silently
break plugin discovery. The agent then has `hud_display` / `hud_dismiss`
tools; YouTube links play as embedded video, `position` left/right lets it
fly in multiple panels from different vectors.

## 6. Verify everything

```bash
scripts/jarvis-health.sh   # all five rows OK
scripts/jarvis-smoke.sh    # synthesized voice turn through the full stack (macOS)
```

Then the real test: click the ring and ask "what's in your memory file?" —
a real agent answers with real file contents.

## Lokale neuronale Stimme (Piper)

Seit 2026-09-07 spricht JARVIS lokal mit Piper, weil das ElevenLabs-Konto auf
dem Free-Tier aufgebraucht ist und die eingebauten macOS-Stimmen die alten
Kompakt-Stimmen sind.

```bash
python3.11 -m venv ~/.hermes/piper-venv
~/.hermes/piper-venv/bin/pip install piper-tts
~/.hermes/piper-venv/bin/python -m piper.download_voices \
  --download-dir ~/.hermes/piper-voices de_DE-thorsten-high
```

Die Bridge findet beides an diesen Standardpfaden von selbst. Abweichend:
`JARVIS_PIPER_BIN` und `JARVIS_PIPER_MODEL` in `~/.hermes/.env`.

Reihenfolge der Stimmen: ElevenLabs (nur mit Guthaben) → Piper → macOS `say`.
`JARVIS_TTS_FALLBACK` steuert sie (`piper`, `macos`, oder `""` zum Abschalten);
der Antwort-Header `X-JARVIS-Speech-Provider` sagt, wer tatsächlich gesprochen
hat. Andere deutsche Stimmen listet `python -m piper.download_voices` ohne
Argument, z. B. `de_DE-kerstin-low` oder `de_DE-thorsten_emotional-medium`.

### Warmer Piper-Dienst

`com.jarvis.piper` hält das Sprachmodell geladen und lauscht auf
`127.0.0.1:8789`. Ohne ihn lädt die Bridge das 109-MB-Modell bei jedem Satz neu
— rund eine Sekunde, jedes Mal.

```bash
cp scripts/jarvis-piper-server.py ~/.hermes/services/
cp launchd/com.jarvis.piper.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.jarvis.piper.plist
curl -s http://127.0.0.1:8789/health     # {"ok": true, "warm": [...]}
```

Die Bridge nutzt ihn automatisch und fällt auf die CLI zurück, wenn er steht.

**Wichtig für alle JARVIS-Dienste: `ProcessType` muss `Interactive` sein.**
Mit `Background` drosselt macOS die CPU des Jobs, und Kindprozesse erben das —
derselbe Satz brauchte 1,2 s im Terminal und 9,2 s über die gedrosselte Bridge.

### Bessere Stimme: OpenAI TTS mit Persona

Lokale deutsche TTS hat eine Qualitätsdecke, und Piper ist sie. Wer darüber
hinaus will, braucht ein Cloud-Modell — aber eines, das nach Verbrauch
abrechnet statt nach einem Monatskontingent, das leer läuft.

```bash
# in ~/.hermes/.env
OPENAI_API_KEY=sk-...
JARVIS_TTS_OPENAI_VOICE=ash          # ash, onyx, ballad, sage, verse, …
```

Danach erscheint „OpenAI (Cloud)" ganz oben in der Stimmenauswahl der App.

Der eigentliche Grund für diesen Anbieter ist nicht die Klangqualität allein,
sondern dass sich die **Persona vorgeben** lässt:

```bash
JARVIS_TTS_OPENAI_INSTRUCTIONS="Sprich wie ein britischer Butler: ruhig, trocken, unaufgeregt, mit leiser Ironie. Tiefe, warme Stimme, gemessenes Tempo, kein Enthusiasmus."
```

Das ist der Unterschied zu jeder lokalen Stimme: die klingt, wie sie klingt.

Angefordert wird `response_format: pcm`, also 24 kHz 16-bit mono — byteweise das
Format, das die App ohnehin abspielt, deshalb wird nichts umgerechnet. Fällt die
Cloud aus, übernimmt sofort die lokale Stimme; stumm wird JARVIS nie.
