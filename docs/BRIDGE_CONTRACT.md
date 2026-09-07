# JARVIS Bridge — API contract for the native app

Status: **verified live on 2026-09-02** against `bridge/jarvis_bridge.py`.
Owner of this document: Claude Code (backend). Consumer: Codex (`apple/`).

This is the authoritative contract for the Swift client. Backend will not change
endpoints, payloads, auth, error semantics, or the port without updating this
file first.

## 1. Transport

| Item | Value |
|---|---|
| Port | **8770** (changed from 8766 — see §7) |
| Local base URL | `http://127.0.0.1:8770` |
| Tailnet base URL | `http://macbook-air-von-marlon.tailfb3c35.ts.net:8770` |
| Bind default | `127.0.0.1` (`JARVIS_BRIDGE_HOST`) |
| Scheme | plain HTTP; confidentiality comes from Tailscale, not TLS |
| Server | `ThreadingHTTPServer`, one thread per request |

The bridge is never exposed to the public internet. Reachability off-device is
provided by `tailscale serve --bg --http=8770 http://127.0.0.1:8770`.

## 2. Authentication

Every endpoint except `GET /` requires the app token:

```
Authorization: Bearer <JARVIS_APP_TOKEN>
```

`X-Jarvis-Token: <token>` is accepted as an equivalent fallback. Comparison is
constant-time. The token lives in `~/.hermes/.env` on the Mac and is generated
by `scripts/setup-mac.sh`; it is never printed and never committed.

The Hermes API key (`API_SERVER_KEY`) stays on the Mac. **The phone never holds
it** — the bridge holds it and speaks to Hermes on the app's behalf.

Missing or wrong token → `401 {"error": "Nicht autorisiert"}`.

## 3. Endpoints

### `GET /` — service banner (open, no auth)
```json
{"service": "JARVIS Bridge", "auth": "required"}
```
Use this for a reachability probe that must not require a token.

### `GET /health` — auth
`200` when Hermes is reachable, `503` when it is not.
```json
{"ok": true, "hermes": {"status": "ok", "platform": "hermes-agent", "version": "0.20.6"}}
```

### `POST /chat` — auth
Request:
```json
{"message": "…", "conversation": "jarvis-apple", "client_run_id": "dash_9f2c…"}
```
- `message`: required, 1–20 000 chars.
- `client_run_id`: optional correlation id, `[A-Za-z0-9_.:-]`, max 64 chars.
  Pass one if you want to be able to cancel this turn; see `POST /stop`.
- `conversation`: optional, defaults to `jarvis-apple`, max 80 chars. Acts as
  the session key; the bridge maps it to a Hermes session and serializes
  concurrent turns per conversation with a lock.

Response `200`:
```json
{"text": "BRIDGE OK", "tools": [], "run_id": "run_3ab153cf…", "duration_ms": 32265}
```
- `tools`: `[{"name": "…", "preview": "…≤200 chars"}]`, tool names starting with
  `_` are filtered out.
- `run_id`: pass to `POST /stop` to cancel.

If the stored Hermes session has expired the bridge transparently retries once
with a fresh session, so the client does not need to handle session rotation.

### `POST /stop` — auth

Two addressing modes; supply **exactly one**. Supplying both is a `400`.

```json
{"run_id": "run_…"}
```
```json
{"client_run_id": "dash_9f2c…"}
```

`run_id` is unchanged, for a client that already holds one.

`client_run_id` (added 2026-09-04) exists because `POST /chat` is synchronous:
it returns `run_id` only after the turn ends, so a client cannot use it to
cancel the turn that is actually running. Pass an arbitrary correlation id of
your own on `POST /chat` (optional, `[A-Za-z0-9_.:-]`, max 64 chars) and cancel
with the same value.

**There is deliberately no way to cancel "the conversation".** A conversation is
shared by the iPhone app, the Mac app and the dashboard at once, so a
conversation-scoped stop would cancel whichever surface happened to be running —
possibly someone else's turn. A caller can only ever cancel its own run.

A cancel that arrives before Hermes emits `run.started` is recorded and applied
the moment the run appears; if the turn is still queued behind another client's
turn it never starts at all.

Responses (all `200` unless noted):

| Case | Body |
|---|---|
| Hermes reported the run stopped | `{"status": "stopped", "stopped": true, "run_id": "run_…"}` |
| Hermes accepted the interrupt | `{"status": "stopping", "stopped": false, "run_id": "run_…"}` |
| Turn not started yet | `{"status": "pending", "stopped": false, "error": "…"}` |
| No such client_run_id | `{"status": "unknown", "stopped": false, "error": "…"}` |
| Neither field / both fields / malformed id | `400 {"error": "…"}` |

`stopped` is `true` **only** when Hermes confirmed the run is dead. `"stopping"`
means the interrupt was accepted, not that the run has ended — do not report a
successful cancellation to the user on that basis.

### `POST /wake` — auth
No body required. With no relay configured returns `{"awake": true, "relay": false}`.
With `JARVIS_RELAY_URL` set it proxies to the relay's `/wake` and returns the
relay payload plus `{"awake": true, "relay": true}`.

### `GET /files?path=<abs path>` — auth
```json
{"path": "/Users/marlon/Documents", "parent": "/Users/marlon",
 "items": [{"name": "…", "path": "…", "is_directory": false,
            "size": 1234, "modified": 1756800000.0}]}
```
Directories sort first, then case-insensitive by name. Dotfiles are omitted.
Capped at **1000 items** — the client must not assume the listing is complete.
`modified` is a Unix epoch **Double**, not an ISO string.

### `GET /files/download?path=<abs path>` — auth
`application/octet-stream` with `Content-Length` and
`Content-Disposition: attachment; filename="…"`.

## 4. Error semantics

| Status | Meaning | Body |
|---|---|---|
| 400 | Validation failure (missing/oversized message, bad `run_id`, bad body size) | `{"error": "<German text>"}` |
| 401 | Missing/invalid token | `{"error": "Nicht autorisiert"}` |
| 403 | Path outside the allowed roots, or a blocked segment | `{"error": "…"}` |
| 404 | Unknown route, or file not found | `{"error": "Nicht gefunden"}` |
| 502 | Hermes unreachable or failed | `{"error": "…"}` |
| 503 | `/health` only — Hermes not reachable | `{"ok": false, …}` |

**Error strings are German and are user-facing.** They are sanitized
(`_safe_error`) so they do not leak internal URLs or the key. The client may show
them directly, but should not parse them — branch on the status code.

## 5. Limits and timeouts

| Limit | Value |
|---|---|
| Request body | 64 KiB |
| `message` | 20 000 chars |
| `conversation` | 80 chars |
| Directory listing | 1000 entries |

Server-side upstream timeouts: `/health` 5 s, `/chat` 300 s, `/wake` 90 s, other
Hermes calls 20 s.

> **Client timeout:** two verified real chat turns took **32.3 s** and
> **39.3 s**. The Swift client currently sets `timeout: 90` on `chat(...)` in
> `JarvisAPIClient` — that is only ~2.3x headroom over the slower measurement,
> and the two samples already vary by 22%. Recommend raising to **120 s**; a slower model or a tool-using turn can plausibly exceed
> 90 s. Current values elsewhere are fine: health 6 s, files 20 s, download
> 120 s, wake 100 s. The first request after bridge start is slower (cold
> start) — do not treat a single early timeout as the bridge being down.

## 6. File access sandbox

Paths are `expanduser().resolve()`d, then required to be equal to or beneath one
of `JARVIS_FILE_ROOTS` (`os.pathsep`-separated; defaults to the home directory,
set to `~/Documents` by `setup-mac.sh`). Any path whose relative parts contain
`.ssh`, `.gnupg`, `.hermes`, or `Keychains` is rejected with 403. Symlink
escapes are covered because resolution happens before the check.

## 7. Port change — action required in `apple/`

The bridge previously defaulted to **8766**. That collided with the voice
server, which binds every entry of `server.yaml`'s `tls_ports: [443, 8766]`
(`server/server.py:1599`), and `server/scripts/jarvis-stop.sh` also kills 8766 —
so stopping the voice server would kill the bridge. The bridge has moved to
**8770**. Voice server ports (8765, 443, 8766, 9443) are unchanged.

Backend files already updated: `bridge/`, `relay/`, `launchd/com.jarvis.bridge.plist`,
`scripts/setup-mac.sh`, `docs/PHASE1_TAILSCALE.md`, `docs/PHASE2_BEWERTUNG.md`,
`docs/CODEX_FIX_IOS_BUILD.md`.

Codex must update `apple/`. Referenced by **symbol, not line number** — these
files were being edited while this document was written, so line numbers drift:

1. `AppModel.defaultServerURL` (in `apple/Sources/Stores/AppModel.swift`) —
   change the port from `8766` to `8770`.
2. The stale-URL migration predicate in the same file (the branch testing
   `contains("jarvis.local")` / `hasSuffix(":8765")` / the bare
   `http://macbook-air-von-marlon:8766` equality) must also match a saved
   `:8766` on the tailnet host. Existing installs may already hold the
   colliding 8766 value, so without this they silently keep pointing at the
   voice server's TLS port.
3. `SettingsView` uses `AppModel.defaultServerURL` as its `TextField`
   placeholder, so it follows item 1 automatically — no separate edit needed.
4. Consider raising the `chat(...)` timeout from 90 s to 120 s (see §5).

## 8. Port map (authoritative)

| Port | Service | Bind |
|---|---|---|
| 8642 | Hermes Agent API | 127.0.0.1 |
| 8765 | Voice server, plain `ws://` | 0.0.0.0 |
| 443, 8766 | Voice server TLS (`tls_ports`) | 0.0.0.0 |
| 8767 | Remote worker stats | remote host |
| 8768 | Remote worker STT | remote host |
| **8770** | **JARVIS Bridge** | **127.0.0.1** |
| 9119 | Hermes dashboard | 127.0.0.1 |
| 9443 | Dashboard TLS reverse proxy | 0.0.0.0 |

Startup order: Hermes (8642) → bridge (8770) → voice server → dashboard proxy.
The bridge degrades gracefully to `503` on `/health` and `502` on `/chat` while
Hermes is down, so ordering is a preference, not a hard requirement.

## 9. Verification performed

```
110 passed   full Python suite  (pytest -q, offline, deterministic)
 15 passed   bridge/test_bridge.py + relay/test_relay.py
     OK      plutil -lint on all three launchd plists
     200     GET  /health  with token  → hermes 0.20.6, 0.23 s
     401     GET  /health  without token
     200     GET  /files?path=~/Documents
     200     POST /chat → {"text":"BRIDGE OK","run_id":"run_3ab153cf…"}, 32.3 s
```

Bridge on 8770 was verified listening simultaneously with a process on 8766,
confirming the collision is resolved.

### Post-deploy verification (deployed launchd service, 2026-09-02)

`scripts/setup-mac.sh` was run. Existing `.env` tokens were preserved (no
regeneration). Deployed `~/.hermes/services/jarvis_bridge.py` and the installed
LaunchAgent are byte-identical to the repo copies.

```
   running   launchd gui/501/com.jarvis.bridge, pid 4873, never exited
      8770   bridge LISTEN
      8642   hermes LISTEN (gateway restarted cleanly)
      8766   connection refused — old bridge port released to the voice server
       401   GET  /health  without token
       200   GET  /health  with token → hermes 0.20.6, 0.22 s
       200   POST /chat → {"text":"DEPLOY OK","run_id":"run_9e8210c8…"}, 39.3 s
```

## Native Erweiterungen vom 2026-09-06 (vorbereitet)

`GET /activity?client_run_id=<ID>` benötigt denselben App-Bearer wie `/chat`.
Antwort: `{"phase":"tool","tool":"web_search"}`. Phasen: `queued`, `thinking`,
`tool`, `answering`, `stopping`, `unknown`. Nur aktive korrelierte Aufträge
werden gehalten; `unknown` bedeutet nicht nachgewiesenen Erfolg. Keine Texte,
Tool-Argumente oder internen Hermes-Run-IDs im Status. Eine ID ist keine
separate Benutzerberechtigung: wie bisher gilt das gemeinsame App-Token.

`POST /speech`, JSON `{"text":"Hallo"}`, benötigt App-Bearer und 1–600
Unicode-Codepoints. Die Bridge leitet ausschließlich an `127.0.0.1:8788` weiter,
ohne HTTP-Proxies, Redirects oder Hermes-Key. Antwort ist
`application/x-ndjson`: Audioframes mit `sample_rate:24000`,
`format:"pcm_s16le"` und Base64-`data`, gefolgt von `{"type":"done"}`.
`429` bedeutet belegt; `503` bedeutet Worker nicht verfügbar. Ein Fehler nach
HTTP-200 erscheint als Errorframe. Der Client darf ohne Done nicht von einer
vollständigen Ausgabe ausgehen.

Dauerhafte Aktivierung dieser Erweiterungen ist aktuell noch durch die
angefragte ausdrückliche Dienstfreigabe blockiert. Sie sind getestet und in
Build 8 integriert, aber noch nicht in `~/.hermes/services/` ausgerollt.

## Stimmenauswahl (2026-09-06)

Zwei Ergänzungen. Der Anbieter-API-Key bleibt auf dem Mac; die App sieht nur
Namen und Kennungen.

### `GET /voices`

Bearer-Token wie überall. Antwort:

```json
{
  "provider": "elevenlabs",
  "voices": [
    {"id": "onwK4e9ZLuTAKqWW03F9", "name": "Daniel - Steady Broadcaster",
     "accent": "british", "gender": "male", "description": "formal"}
  ],
  "selected": "onwK4e9ZLuTAKqWW03F9"
}
```

`provider` ist `local` oder `elevenlabs`; bei `local` ist `voices` leer.
`selected` ist die auf dem Mac konfigurierte Vorgabe. Die Liste wird 15 Minuten
zwischengespeichert; `?refresh=1` erzwingt einen Neuabruf. Fällt der Anbieter
aus, kommt `503` mit `{"error": ...}` — die App muss dann ihre Auswahl behalten
und nicht zurücksetzen.

### `POST /speech` nimmt jetzt `voice_id`

```json
{"text": "Guten Abend, sir.", "voice_id": "JBFqnCBsd6RMkjVDRZzb"}
```

`voice_id` ist optional. Fehlt es oder ist es leer, gilt die Mac-Vorgabe.

Die Bridge prüft die Kennung gegen die Liste aus `/voices`, bevor sie den
Anbieter aufruft — sonst könnte ein Client das Kontingent des Nutzers auf
beliebige Kennungen verbrauchen. Ist der Katalog gerade nicht abrufbar, greift
die Mac-Vorgabe statt eines Fehlers.

Fehlercodes:

| Code | Bedeutung | Verhalten der App |
|---|---|---|
| `400` | Kennung syntaktisch ungültig oder nicht im Konto | Auswahl zurücksetzen, Liste neu laden |
| `402` | Bibliotheks-Stimme, Tarif erlaubt sie nicht | Meldung zeigen, vorinstallierte Stimme anbieten |
| `429` | Kontingent erschöpft | Auf Systemstimme zurückfallen |
| `503` | Anbieter nicht erreichbar | Auf Systemstimme zurückfallen |

Der `402`-Fall ist kein Randfall: `/voices` listet Bibliotheks-Stimmen in jedem
Tarif auf, aber nur bezahlte Tarife dürfen mit ihnen sprechen. Die Liste allein
ist also keine Zusage, dass eine Stimme funktioniert.

### Datum und Uhrzeit in jedem Turn

`POST /chat` und `/chat/stream` stellen der Nachricht eine Kontextzeile voran:

```
[Kontext: Sonntag, 6. September 2026, 18:13 Uhr]
```

Das Modell hat sonst keine Uhr und erfindet den Wochentag. Die App muss dafür
nichts tun; die Zeile entsteht in der Bridge und erscheint nicht in der
Antwort.

## Anhänge und eingefügte Bilder (2026-09-06)

### Antworten tragen `attachments`

`/chat` und der `done`-Frame von `/chat/stream` enthalten zusätzlich:

```json
"attachments": [
  {"kind": "image",  "url": "https://…/eisvogel.jpeg", "title": "nabu.de"},
  {"kind": "video",  "url": "https://youtu.be/…",      "title": "youtu.be"},
  {"kind": "source", "url": "https://…/portraet/",     "title": "NABU"}
]
```

Die Bridge liest sie aus dem Antworttext: Markdown-Bilder und -Links sowie
nackte URLs. `kind` folgt der Endung beziehungsweise dem Host; alles
Unbekannte wird `source`. Höchstens zwölf Einträge, Reihenfolge wie im Text,
Doppelte einmal.

**Nur `http` und `https` überleben.** Ein `file:`- oder `data:`-Verweis aus
einer Antwort würde sonst ins Gerät greifen oder beliebige Bytes einbetten.

Der Antworttext bleibt unverändert. Die App entfernt Links vor der
Sprachausgabe (`SpeechText.withoutLinks`), weil eine vorgelesene URL
unerträglich ist; angezeigt wird der Text vollständig.

### `POST /upload`

```json
{"data": "<base64 des Bildes>"}
```

Antwort `{"path": "/Users/…/.hermes/jarvis-uploads/<hex>.png", "name": "<hex>.png"}`.

Der Typ wird **an den Magic Bytes** erkannt, nie am Namen oder an einer
Angabe des Clients: PNG, JPEG, GIF, WebP, HEIC. Alles andere ergibt `400`.
Höchstens 10 MB. Der Zielordner ist fest, der Dateiname wird erzeugt
(`secrets.token_hex`), Ordner `0700`, Datei `0600`.

### `POST /chat` und `/chat/stream` nehmen `image_path`

```json
{"message": "Was ist das?", "conversation": "…", "image_path": "/Users/…/jarvis-uploads/<hex>.png"}
```

Die Bridge prüft, dass der Pfad **innerhalb des Uploadordners** liegt, und
stellt der Nachricht dann eine Zeile voran, die den Agenten auf
`vision_analyze` verweist. Jeder andere Pfad ergibt `400` — sonst wäre das ein
Weg, den Agenten beliebige Dateien auf dem Mac lesen zu lassen.

## Lokale Ersatzstimme und Aufgaben-Board (2026-09-07)

### `POST /speech` fällt auf die macOS-Stimme zurück

Der ElevenLabs-Account ist auf dem Free-Tier und das Kontingent ist
aufgebraucht (10.000/10.000 Zeichen), also antwortet ElevenLabs auf jede
Anfrage mit HTTP 401. Vorher wurde daraus ein 503 und JARVIS blieb stumm.

Die Bridge spricht jetzt lokal weiter, wenn der konfigurierte Anbieter nicht
kann — bei 401 (Kontingent), 402 (Stimme braucht bezahlten Tarif), 429
(Rate Limit), fehlendem Schlüssel, und ebenso wenn der neuronale Worker auf
`127.0.0.1:8788` nicht läuft.

- Antwort bleibt **exakt dasselbe NDJSON** wie bisher: `{"type":"audio",
  "sample_rate":24000, "format":"pcm_s16le", "data":"<base64>"}`, abgeschlossen
  mit `{"type":"done"}`. **`NeuralSpeechPlayer` braucht keine Änderung.**
- Neuer Antwort-Header `X-JARVIS-Speech-Provider: elevenlabs | local | macos`.
  Optional für die App: bei `macos` liesse sich ein dezenter Hinweis anzeigen,
  dass gerade die Ersatzstimme läuft. Kein Pflicht-Feld.
- Steuerung über `~/.hermes/.env`:
  `JARVIS_TTS_FALLBACK=macos` (Default; `""` schaltet ab und liefert wieder den
  Originalfehler) und `JARVIS_TTS_MACOS_VOICE=<Name>`. Ohne gesetzte Stimme
  wählt die Bridge die beste installierte de_DE-Stimme (aktuell "Anna"), damit
  nicht eine englische Systemstimme deutsche Sätze liest.
- Nur wenn `say` fehlt oder ebenfalls scheitert, kommt der ursprüngliche Fehler
  (503/429/402) unverändert zurück.

Verifiziert am laufenden Dienst: HTTP 200, Header `macos`, 4,71 s Audio bei
24 kHz mono.

### `GET /runs` — alle laufenden Turns (neu)

Für die Multitasking-Anzeige. Gleicher App-Bearer wie `/chat`.

```json
{"count": 1,
 "runs": [{"client_run_id": "probe-1788765958",
           "phase": "thinking",
           "tool": "",
           "conversation": "claude-probe",
           "seconds": 6.2}]}
```

- `phase`: `queued | thinking | answering | tool | stopping` — dieselben Werte
  wie `/activity`.
- `seconds`: Alter des Turns, längster zuerst.
- Enthält **nie** Prompt, Antwort oder Tool-Argumente (per Test abgesichert).
- `GET /activity?client_run_id=…` ist unverändert; `/runs` ist additiv.

Wichtig für die Erwartungshaltung in der UI: Turns **derselben** Conversation
serialisieren in der Bridge. Der zweite steht als `queued`, bis der erste
fertig ist. Echte Parallelität gibt es nur über **verschiedene**
`conversation`-Werte — wenn die App mehrere Aufgaben gleichzeitig laufen lassen
soll, muss sie dafür getrennte Conversations vergeben.

Verifiziert am laufenden Dienst: leeres Board `{"runs":[],"count":0}`, ohne
Token 401, und ein echter Turn erschien mit `thinking` → `answering` und
verschwand beim Abschluss.

### `GET /notifications`, `POST /notify`, `POST /notifications/read` (neu)

Der Kanal, über den JARVIS von sich aus etwas melden kann — statt einer
macOS-Mitteilung, die das Betriebssystem ist und nicht JARVIS. Gleicher
App-Bearer wie `/chat`.

```
GET  /notifications?since=<id>&unread=1
POST /notifications/read   {"through": <id>}
POST /notify               {"kind","title","text"}
```

```json
{"notifications": [{"id": 1, "kind": "whatsapp_reply", "title": "Rici",
                    "text": "hat geantwortet", "at": 1788772924.37,
                    "read": false}],
 "unread": 1, "latest": 1}
```

- `kind`: `whatsapp_reply | task | info`; alles andere wird mit 400 abgelehnt.
- `title` ≤ 80, `text` ≤ 200 Zeichen, beide auf eine Zeile normalisiert.
- Warteschlange auf 50 begrenzt, überlebt einen Bridge-Neustart, Datei 600.
- `latest` ist der Cursor für das nächste `since`.
- Pull statt Push mit Absicht: ein verpasster Moment wird zu einer späten
  Benachrichtigung, nie zu einer verlorenen, und nichts weckt ein Telefon.
- `POST /notify` schreiben JARVIS' eigene Helfer auf dieser Maschine, heute der
  WhatsApp-Antwort-Watcher. Nachrichteninhalt wird nie übertragen.

Die zugehörige UI-Vorgabe steht in `docs/APP_UI_MULTITASKING_NOTIFICATIONS.md`.

### `POST /chat` und `/chat/stream` nehmen `parallel` (neu)

`{"message": …, "conversation": "jarvis-apple", "client_run_id": …,
  "parallel": true}`

Ohne das Feld ändert sich nichts: ein zweiter Turn derselben Conversation wartet
wie bisher. Mit `parallel: true` läuft er sofort, in einer Nebenspur
(`jarvis-apple#2` … `#4`), und die Antwort nennt die tatsächliche Conversation:

```json
{"text": "…", "conversation": "jarvis-apple#2", "run_id": "…", "tools": []}
```

Hintergrund: Hermes hält eine Turn-Lease **pro Session**
(`session_turn_leases`, Schlüssel ist die Conversation). Zwei Turns in einer
Session können daher nicht überlappen, egal wie die Bridge gebaut ist — das
Entfernen des Bridge-Locks hätte die Warteschlange nur eine Ebene tiefer
verschoben. Gemessen: zwei Turns in einer Conversation 2,8 s + 7,7 s, dieselben
zwei in getrennten Conversations 2,3 s und 2,7 s Wanduhr.

Eine Nebenspur trägt die Historie der Hauptunterhaltung **nicht**. Das Flag ist
für „mach beides gleichzeitig", nicht für eine Rückfrage. Maximal vier Spuren
pro Name, danach wird gewartet — sonst öffnet ein Client ohne Ende Sessions.

Verifiziert am laufenden Dienst: drei Aufgaben unter einem Namen, 1,8 / 1,9 /
2,1 s, Gesamtdauer 3 s; `/runs` zeigte drei Einträge gleichzeitig in
`answering`, jeder in seiner eigenen Spur.
