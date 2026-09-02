# JARVIS runbook

Operating the running system. For the app-facing API see `BRIDGE_CONTRACT.md`.

## Services

| Port | Service | Bind | Managed by |
|---|---|---|---|
| 8642 | Hermes Agent API (the brain) | 127.0.0.1 | `hermes gateway` |
| 8770 | JARVIS Bridge (native app) | 127.0.0.1 | `com.jarvis.bridge` |
| 8765 | Voice server, plain `ws://` | 0.0.0.0 | `com.jarvis.voice` |
| 443, 8766 | HUD over TLS | 0.0.0.0 | `com.jarvis.voice` |
| 9443 | Dashboard TLS reverse proxy | 0.0.0.0 | `com.jarvis.voice` |
| 9119 | Hermes dashboard | 127.0.0.1 | `com.jarvis.dashboard` |

All three launchd jobs use `KeepAlive`, so a crashed service comes back on its
own (voice takes ~80 s — most of it warming the STT model).

## Check everything

```bash
server/scripts/jarvis-health.sh
```

Five OK lines is a healthy system. It reports reachability, not auth: the
dashboard proxy answering 401 without a token is correct.

```bash
launchctl print gui/$(id -u)/com.jarvis.voice | grep -E 'state|pid|last exit'
```

## Start / stop

```bash
launchctl kickstart -k gui/$(id -u)/com.jarvis.voice
```

`server/scripts/jarvis-stop.sh` frees the voice ports (443, 8765, 8766, 9443)
only — it deliberately leaves the bridge on 8770 alone. With `KeepAlive` set,
launchd restarts the job a few seconds later; to stop it for real, `launchctl
bootout gui/$(id -u)/com.jarvis.voice` first.

## Logs

```bash
tail -f ~/Library/Logs/jarvis-voice.log
```

`~/Library/Logs/jarvis-dashboard.log` and `~/.hermes/logs/jarvis-bridge.log`
for the other two. The voice plist sets `PYTHONUNBUFFERED=1`; without it Python
block-buffers into the log file and the job looks hung when it is merely quiet.

## Two auth schemes — do not mix them

| Surface | Header |
|---|---|
| Bridge (8770) | `Authorization: Bearer <JARVIS_APP_TOKEN>` (or `X-Jarvis-Token`) |
| Voice/HUD (443, 8765) | `X-Jarvis-Token: <JARVIS_HUD_TOKEN>` (or `jarvis_token` cookie) |

The HUD ignores `Authorization: Bearer` entirely and answers 401 — that is the
single easiest way to waste half an hour here. WebSocket clients without an
`Origin` header pass the token as `?token=...`.

Both tokens live in `~/.hermes/.env` (mode 600, never committed). Copy one to
the clipboard without printing it:

```bash
grep -m1 '^JARVIS_APP_TOKEN=' ~/.hermes/.env | cut -d= -f2- | tr -d '\n' | pbcopy
```

`JARVIS_HUD_TOKEN` matters: with it unset the server binds `0.0.0.0` with the
whole `/api` surface, `/api/say` and the dashboard proxy open to anyone on the
network. The server prints a loud SECURITY WARNING at startup in that state.

## Remote access (Tailscale)

```bash
tailscale serve status
```

The bridge is proxied at `http://<host>.<tailnet>.ts.net:8770`. The HUD is
reached directly on 443 over the tailnet using the self-signed cert, whose SAN
list `server/scripts/make-certs.sh` populates with the MagicDNS name and the
100.x address. Phones must trust `server/certs/cert.pem` once (downloadable
from the HUD as `jarvis.cer`).

To drop the cert warning entirely, enable HTTPS certificates for the tailnet in
the Tailscale admin console, then `tailscale serve --bg --https=443
https+insecure://127.0.0.1:443`. Without that setting the command hangs waiting
on cert provisioning.

## Voice

Speech in and out works with no cloud account: `voice.fallback: macos` uses the
built-in `say`. For the ElevenLabs voice, put `ELEVENLABS_API_KEY` in
`~/.hermes/.env` **and** replace the `YOUR_ELEVENLABS_VOICE_ID` placeholder
under `voice:` in `server/config/server.yaml` — the key alone is not enough.

Test the whole pipeline without a microphone:

```bash
say -o /tmp/t.aiff "What is two plus two" && afconvert -f WAVE -d LEI16@16000 -c 1 /tmp/t.aiff /tmp/t.wav
```

then, with `JARVIS_HUD_TOKEN` exported,
`server/.venv/bin/python server/scripts/ws_e2e_test.py /tmp/t.wav`. A healthy
run prints TRANSCRIPT, RESPONSE, and a non-zero AUDIO_BYTES.

## Gotchas that cost time

- **`server/.venv` needs Python 3.11+.** The repo-root `.venv` is Python 3.9
  and is for the test suite only; current torch wheels do not support 3.9.
- **`brew install portaudio` before pip**, or PyAudio fails to build a wheel and
  takes RealtimeSTT down with it.
- **The bridge runs a deployed copy** at `~/.hermes/services/jarvis_bridge.py`,
  not the repo file. Editing `bridge/jarvis_bridge.py` changes nothing until
  `scripts/setup-mac.sh` redeploys it.
- **8766 belongs to the voice server**, not the bridge. It was moved to 8770
  precisely because `jarvis-stop.sh` kills 8766.
