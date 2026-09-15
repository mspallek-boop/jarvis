#!/usr/bin/env python3
"""JARVIS phones someone for the user: Fairytel SIP line + OpenAI Realtime voice.

    call.py start --to 06641234567 --callee "Friseur X" [--minutes 6] < task.txt
    call.py run --id ID          the call itself; `start` spawns it detached
    call.py status [--id ID]     JSON of one call, the latest by default
    call.py check [--sip] [--openai]   test the line and the voice without calling anyone

Credentials come from ~/.hermes/.env (FAIRYTEL_SIP_USER, FAIRYTEL_SIP_PASSWORD,
OPENAI_API_KEY) and never appear in arguments, logs or results. Every call is
one file, ~/.hermes/phone/calls/<id>.json: the task, then outcome, summary and
transcript. When a call ends, jarvis-notify puts the result into the app.

Audio never changes format on the way: G.711 from the phone network goes to
the model as 8 kHz mu-law and back. Only an A-law line is translated, by table.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import logging
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import policy  # noqa: E402
from sip import CallFailed, SipAccount, SipError, SipPhone  # noqa: E402

HOME = Path.home()
ENV_FILE = Path(os.environ.get("JARVIS_PHONE_ENV", HOME / ".hermes/.env"))
STATE = Path(os.environ.get("JARVIS_PHONE_DIR", HOME / ".hermes/phone"))
CALLS = STATE / "calls"
NOTIFY = Path(os.environ.get("JARVIS_PHONE_NOTIFY", HOME / ".hermes/bin/jarvis-notify"))
REALTIME_URL = os.environ.get("PHONE_REALTIME_URL", "wss://api.openai.com/v1/realtime")
ACTIVE = ("queued", "dialing", "ringing", "in_call")
FATAL_CODES = {"insufficient_quota", "invalid_api_key", "model_not_found", "session_expired"}
# IPv6 to api.openai.com hangs on this line while IPv4 answers in milliseconds;
# racing both (RFC 8305) keeps the connect from sitting out a v6 timeout.
HAPPY_EYEBALLS = 0.25
# Fairytel's own announcement when the prepaid balance is empty (heard 2026-09-11).
CREDIT_ANNOUNCEMENT = "kein ausreichendes guthaben"
OUTCOMES = {
    "erledigt": "erledigt", "teilweise": "teilweise erledigt", "nicht_erledigt": "nicht erledigt",
    "rueckfrage_noetig": "Rückfrage nötig", "mailbox": "Mailbox", "abgelehnt": "Gespräch abgelehnt",
}

log = logging.getLogger("jarvis.phone")


def env(name: str, default: str = "") -> str:
    if os.environ.get(name):
        return os.environ[name]
    try:
        for line in ENV_FILE.read_text().splitlines():
            key, _, value = line.partition("=")
            if key.strip() == name and value.strip():
                return value.strip().strip("'\"")
    except OSError:
        pass
    return default


# --- G.711: A-law <-> mu-law by table (Sun reference algorithms) -------------

def _ulaw_to_linear(u: int) -> int:
    u = ~u & 0xFF
    t = (((u & 0x0F) << 3) + 0x84) << ((u & 0x70) >> 4)
    return (0x84 - t) if u & 0x80 else (t - 0x84)


def _alaw_to_linear(a: int) -> int:
    a ^= 0x55
    t = (a & 0x0F) << 4
    seg = (a & 0x70) >> 4
    if seg == 0:
        t += 8
    elif seg == 1:
        t += 0x108
    else:
        t = (t + 0x108) << (seg - 1)
    return t if a & 0x80 else -t


def _segment(value: int, ends: tuple) -> int:
    for i, end in enumerate(ends):
        if value <= end:
            return i
    return len(ends)


def _linear_to_ulaw(sample: int) -> int:
    sample >>= 2
    mask = 0xFF
    if sample < 0:
        sample, mask = -sample, 0x7F
    sample = min(sample, 8159) + 0x21
    seg = _segment(sample, (0x3F, 0x7F, 0xFF, 0x1FF, 0x3FF, 0x7FF, 0xFFF, 0x1FFF))
    if seg >= 8:
        return 0x7F ^ mask
    return ((seg << 4) | ((sample >> (seg + 1)) & 0x0F)) ^ mask


def _linear_to_alaw(sample: int) -> int:
    sample >>= 3
    mask = 0xD5
    if sample < 0:
        sample, mask = -sample - 1, 0x55
    seg = _segment(sample, (0x1F, 0x3F, 0x7F, 0xFF, 0x1FF, 0x3FF, 0x7FF, 0xFFF))
    if seg >= 8:
        return 0x7F ^ mask
    value = (seg << 4) | (((sample >> 1) if seg < 2 else (sample >> seg)) & 0x0F)
    return value ^ mask


A2U = bytes(_linear_to_ulaw(_alaw_to_linear(a)) for a in range(256))
U2A = bytes(_linear_to_alaw(_ulaw_to_linear(u)) for u in range(256))


# --- what the voice is told --------------------------------------------------

def instructions(task: str, principal: str, callee: str, minutes: int) -> str:
    return f"""Du bist JARVIS, ein KI-Assistent, und führst gerade ein echtes Telefonat im Auftrag von {principal}. Du rufst an bei: {callee}.

So beginnst du: Sobald sich jemand meldet, sagst du als Erstes, wer du bist, zum Beispiel: "Guten Tag, hier spricht JARVIS, ein KI-Assistent. Ich rufe im Auftrag von {principal} an." Dann nennst du kurz das Anliegen. Fragt jemand, ob du ein Mensch bist, sagst du ehrlich, dass du eine KI bist.

Regeln, die immer gelten:
- Du hältst dich an den Auftrag unten. Du sagst nichts zu, was dort nicht ausdrücklich erlaubt ist: keine Zahlungen, keine Verträge, keine Kosten, keine anderen Termine oder Zeiten.
- Über {principal} gibst du nur weiter, was im Auftrag steht. Fragt man nach mehr (Adresse, Geburtsdatum, Versicherungs- oder Kontonummer), sagst du, dass {principal} das selbst nachreicht.
- Kannst du etwas nicht entscheiden, sagst du: "Das muss ich mit {principal} abklären, wir melden uns wieder."
- Du erfindest nichts. Weißt du etwas nicht, sagst du das.
- Wiederhole Vereinbartes zur Bestätigung: Datum, Uhrzeit, Name, Ort.
- Möchte das Gegenüber nicht mit einer KI sprechen, bedankst du dich, verabschiedest dich und beendest das Gespräch.
- Fragt das Gegenüber, ob der Anruf etwas kostet, antwortest du: "Nein, für Sie kostet das nichts." Duzt ihr euch, sagst du: "Nein, für dich kostet das nichts."
- In einem Sprachmenü wählst du mit send_dtmf die passende Taste. Auf einer Mailbox hinterlässt du nur dann eine kurze Nachricht, wenn der Auftrag das erlaubt; sonst beendest du das Gespräch.
- Sprich natürlich, freundlich und knapp, in der Sprache des Gegenübers. Keine Monologe.
- Das Gespräch dauert höchstens {minutes} Minuten.
- Wenn alles gesagt ist, verabschiedest du dich. Erst danach rufst du end_call mit dem Ergebnis auf.

Auftrag von {principal}:
{task}
"""


TOOLS = [
    {
        "type": "function",
        "name": "end_call",
        "description": "Beendet das Telefonat. Erst aufrufen, nachdem du dich verabschiedet hast.",
        "parameters": {"type": "object", "properties": {
            "outcome": {"type": "string", "enum": list(OUTCOMES)},
            "summary": {"type": "string", "description": (
                "Zwei bis vier Sätze für den Auftraggeber: was vereinbart wurde, mit wem, "
                "was offen ist. Konkrete Daten und Uhrzeiten nennen.")},
        }, "required": ["outcome", "summary"]},
    },
    {
        "type": "function",
        "name": "send_dtmf",
        "description": "Drückt Tasten im Sprachmenü des Gegenübers, z. B. '1' oder '0#'.",
        "parameters": {"type": "object", "properties": {
            "digits": {"type": "string", "description": "Nur 0-9, * und #"},
        }, "required": ["digits"]},
    },
]


# --- records -----------------------------------------------------------------

def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def record_path(call_id: str) -> Path:
    if not call_id or "/" in call_id or call_id.startswith("."):
        raise policy.PolicyError("Unbekannte Anruf-ID.")
    return CALLS / f"{call_id}.json"


def save(record: dict) -> None:
    CALLS.mkdir(parents=True, exist_ok=True)
    path = record_path(record["id"])
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(record, ensure_ascii=False, indent=1))
    os.chmod(tmp, 0o600)  # transcripts are private
    tmp.replace(path)


def load(call_id: str) -> dict:
    return json.loads(record_path(call_id).read_text())


def latest() -> dict | None:
    records = sorted(CALLS.glob("*.json")) if CALLS.is_dir() else []
    return json.loads(records[-1].read_text()) if records else None


def running_call() -> dict | None:
    for path in sorted(CALLS.glob("*.json")) if CALLS.is_dir() else []:
        try:
            record = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if record.get("status") in ACTIVE and not policy.stale(record.get("created_at", ""),
                                                                record.get("minutes", 15)):
            return record
    return None


def account() -> SipAccount:
    return SipAccount(
        username=env("FAIRYTEL_SIP_USER"),
        password=env("FAIRYTEL_SIP_PASSWORD"),
        domain=env("FAIRYTEL_SIP_DOMAIN", "sip.fairytel.at"),
        auth_username=env("FAIRYTEL_SIP_AUTH_USER"),
        display_name=env("PHONE_DISPLAY_NAME", "JARVIS"),
    )


def missing_credentials() -> list:
    return [name for name in ("FAIRYTEL_SIP_USER", "FAIRYTEL_SIP_PASSWORD", "OPENAI_API_KEY") if not env(name)]


# --- the call ----------------------------------------------------------------

class PhoneCall:
    def __init__(self, record: dict, sip_account: SipAccount, api_key: str):
        self.record = record
        self.api_key = api_key
        self.phone = SipPhone(sip_account, self._on_audio, on_ringing=self._on_ringing)
        self.ws = None
        self.inbound: asyncio.Queue = asyncio.Queue()
        self.heard_speech = False
        self.responded = False
        self.hangup_requested = False
        self.fatal = ""
        self.tasks: list = []
        self.events: dict = {}  # realtime event type -> count, for the record's diagnostics

    # plumbing

    def _on_audio(self, payload: bytes) -> None:
        self.inbound.put_nowait(payload)

    def _on_ringing(self) -> None:
        if self.record["status"] == "dialing":
            self.update(status="ringing")

    def update(self, **fields) -> None:
        self.record.update(fields)
        save(self.record)

    def _say(self, who: str, text: str) -> None:
        text = (text or "").strip()
        if text:
            self.record.setdefault("transcript", []).append({"who": who, "text": text, "at": now_iso()})
            save(self.record)

    async def _send(self, event: dict) -> None:
        if self.ws is not None:
            await self.ws.send(json.dumps(event))

    async def _connect_realtime(self) -> None:
        import websockets

        model = env("PHONE_REALTIME_MODEL", "gpt-realtime-2.1")
        self.ws = await websockets.connect(
            f"{REALTIME_URL}?model={model}",
            additional_headers={"Authorization": f"Bearer {self.api_key}"},
            max_size=None, open_timeout=15, happy_eyeballs_delay=HAPPY_EYEBALLS,
        )
        await self._send({"type": "session.update", "session": {
            "type": "realtime",
            "model": model,
            "output_modalities": ["audio"],
            "instructions": instructions(self.record["task"], env("PHONE_PRINCIPAL", "Marlon Spallek"),
                                         self.record.get("callee") or "unbekannt", self.record["minutes"]),
            "audio": {
                "input": {
                    "format": {"type": "audio/pcmu"},
                    "transcription": {"model": "gpt-4o-mini-transcribe"},
                    "turn_detection": {"type": "semantic_vad", "eagerness": "medium",
                                       "create_response": True, "interrupt_response": True},
                },
                "output": {"format": {"type": "audio/pcmu"}, "voice": env("PHONE_VOICE", "cedar")},
            },
            "tools": TOOLS,
            "tool_choice": "auto",
        }})

    # tasks while the call is up

    async def _forward_audio(self) -> None:
        while True:
            chunk = bytearray(await self.inbound.get())
            while not self.inbound.empty():
                chunk.extend(self.inbound.get_nowait())
            if self.phone.codec == 8:
                chunk = chunk.translate(A2U)
            await self._send({"type": "input_audio_buffer.append", "audio": base64.b64encode(chunk).decode()})

    async def _read_realtime(self) -> None:
        async for raw in self.ws:
            event = json.loads(raw)
            kind = event.get("type", "")
            if kind not in self.events:
                log.info("realtime: first %s", kind)
            self.events[kind] = self.events.get(kind, 0) + 1
            if kind in ("response.output_audio.delta", "response.audio.delta"):
                audio = base64.b64decode(event.get("delta", ""))
                if self.phone.codec == 8:
                    audio = audio.translate(U2A)
                self.phone.rtp.play(event.get("item_id", ""), audio)
            elif kind == "response.created":
                self.responded = True
            elif kind == "input_audio_buffer.speech_started":
                self.heard_speech = True
                cut = self.phone.rtp.clear()
                if cut and cut[0]:
                    await self._send({"type": "conversation.item.truncate", "item_id": cut[0],
                                      "content_index": 0, "audio_end_ms": cut[1]})
            elif kind == "conversation.item.input_audio_transcription.completed":
                self._say("gegenüber", event.get("transcript", ""))
            elif kind in ("response.output_audio_transcript.done", "response.audio_transcript.done"):
                self._say("jarvis", event.get("transcript", ""))
            elif kind == "response.function_call_arguments.done":
                await self._tool(event)
            elif kind == "response.done" and self.hangup_requested:
                self.tasks.append(asyncio.ensure_future(self._hangup_when_drained()))
            elif kind == "error":
                error = event.get("error") or {}
                log.warning("realtime error: %s %s", error.get("code"), error.get("message"))
                if error.get("code") in FATAL_CODES:
                    self.fatal = "Die OpenAI-Stimme ist nicht verfügbar (" + str(error.get("code")) + ")."
                    await self.phone.hangup()
                    return

    async def _tool(self, event: dict) -> None:
        name, call_id = event.get("name"), event.get("call_id")
        try:
            args = json.loads(event.get("arguments") or "{}")
        except ValueError:
            args = {}
        if name == "end_call":
            outcome = str(args.get("outcome", ""))
            self.update(outcome=outcome if outcome in OUTCOMES else "teilweise",
                        summary=str(args.get("summary", "")).strip())
            self.hangup_requested = True
            output = {"ok": True}
        elif name == "send_dtmf":
            sent = self.phone.rtp.send_dtmf(str(args.get("digits", "")))
            self._say("jarvis", f"[Tasten: {sent}]" if sent else "[Tasten nicht möglich]")
            output = {"ok": bool(sent), "sent": sent}
        else:
            output = {"ok": False, "error": "unbekanntes Werkzeug"}
        await self._send({"type": "conversation.item.create", "item": {
            "type": "function_call_output", "call_id": call_id, "output": json.dumps(output)}})
        # No response.create: after end_call the goodbye is said, after a key press
        # the menu speaks next and voice activity starts the reply.

    async def _hangup_when_drained(self) -> None:
        for _ in range(300):  # let the goodbye finish playing, 15 s at most
            if not self.phone.rtp.playing:
                break
            await asyncio.sleep(0.05)
        await asyncio.sleep(0.6)
        await self.phone.hangup()

    async def _open_if_silent(self) -> None:
        await asyncio.sleep(3)
        if not self.heard_speech and not self.responded:
            await self._send({"type": "response.create"})

    async def _time_limit(self) -> None:
        total = self.record["minutes"] * 60
        await asyncio.sleep(max(20, total - 45))
        await self._send({"type": "response.create", "response": {"instructions": (
            "Die Gesprächszeit ist fast vorbei. Fasse das Vereinbarte in einem Satz zusammen, "
            "verabschiede dich höflich und rufe dann end_call auf.")}})
        await asyncio.sleep(45)
        self.record["end_note"] = "Zeitlimit erreicht"
        await self.phone.hangup()

    # the whole call

    async def run(self) -> dict:
        self.update(status="dialing", pid=os.getpid())
        try:
            await self.phone.open()
            await self.phone.register()
            await self._connect_realtime()
            await self.phone.dial(self.record["dial"], ring_timeout=45)
            self.update(status="in_call", answered_at=now_iso())
            reader = asyncio.ensure_future(self._read_realtime())
            self.tasks += [reader, asyncio.ensure_future(self._forward_audio()),
                           asyncio.ensure_future(self._open_if_silent()),
                           asyncio.ensure_future(self._time_limit())]
            ended = asyncio.ensure_future(self.phone.ended.wait())
            await asyncio.wait({ended, reader}, return_when=asyncio.FIRST_COMPLETED)
            if reader.done() and not reader.cancelled() and reader.exception():
                log.warning("realtime connection lost: %s", reader.exception())
                self.fatal = self.fatal or "Die Verbindung zur OpenAI-Stimme ist abgerissen."
            ended.cancel()
            await self.phone.hangup()
            if not reader.done():
                # Speech cut off by the hang-up is still in the input buffer; commit it and
                # give the transcription a moment, or a mailbox greeting leaves no trace.
                await self._send({"type": "input_audio_buffer.commit"})
                await asyncio.sleep(2)
            self._finish(status="done")
        except CallFailed as exc:
            self._finish(status="failed", error=exc.reason)
        except (SipError, OSError) as exc:
            log.warning("call failed: %s", exc)
            self._finish(status="failed", error=f"Technischer Fehler: {exc}")
        except Exception as exc:  # the record must never stay 'in_call' forever
            log.exception("call crashed")
            name = type(exc).__name__
            if "InvalidStatus" in name or "InvalidHandshake" in name:
                self._finish(status="failed", error="OpenAI hat die Verbindung abgelehnt (Key oder Guthaben?).")
            else:
                self._finish(status="failed", error=f"Technischer Fehler: {name}")
        finally:
            for task in self.tasks:
                task.cancel()
            if self.ws is not None:
                await self.ws.close()
            await self.phone.close()
        return self.record

    def _finish(self, status: str, error: str = "") -> None:
        fields = {"status": status, "ended_at": now_iso(), "end_reason": self.phone.end_reason,
                  "diag": {"codec": self.phone.codec, "rtp_in": self.phone.rtp.received,
                           "rtp_out": self.phone.rtp.sent, "events": self.events}}
        if self.record.get("answered_at"):
            answered = datetime.fromisoformat(self.record["answered_at"])
            fields["duration_s"] = int((datetime.now() - answered).total_seconds())
        transcript = self.record.get("transcript", [])
        heard = [t["text"] for t in transcript if t["who"] == "gegenüber"]
        spoke = any(t["who"] == "jarvis" for t in transcript)
        if status == "done" and not spoke and heard and CREDIT_ANNOUNCEMENT in heard[0].lower():
            # Fairytel "answers" an unfunded call itself and plays this; nobody was reached.
            status = fields["status"] = "failed"
            error = "Das Fairytel-Guthaben ist leer; bitte im Kundenbereich aufladen. Angerufen wurde niemand."
        if error or self.fatal:
            fields["error"] = error or self.fatal
        if status == "done" and not self.record.get("outcome"):
            fields["outcome"] = "nicht_erledigt"
            last = f" Zuletzt gehört: „{heard[-1]}“" if heard else ""
            fields["summary"] = "Das Gespräch endete, bevor JARVIS es abschließen konnte." + last
        self.update(**fields)


def notify(record: dict) -> None:
    who = record.get("callee") or record.get("to")
    if record.get("status") == "failed":
        headline, text = f"Anruf bei {who} hat nicht geklappt", record.get("error", "")
    else:
        headline = f"Anruf bei {who}: {OUTCOMES.get(record.get('outcome', ''), 'beendet')}"
        text = record.get("summary") or record.get("error") or "Keine Zusammenfassung – das Gespräch endete vorher."
    try:
        subprocess.run([str(NOTIFY), headline, "--text", text], timeout=30,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        log.warning("jarvis-notify failed")


# --- commands ----------------------------------------------------------------

def out(payload: dict, code: int = 0) -> int:
    print(json.dumps(payload, ensure_ascii=False))
    return code


def cmd_start(args) -> int:
    task = (Path(args.task_file).read_text() if args.task_file else sys.stdin.read()).strip()
    try:
        if not task:
            raise policy.PolicyError("Der Auftrag für das Telefonat fehlt.")
        if len(task) > 4000:
            raise policy.PolicyError("Der Auftrag ist zu lang (höchstens 4000 Zeichen).")
        e164 = policy.normalize(args.to)
        policy.check_number(e164)
        missing = missing_credentials()
        if missing:
            raise policy.PolicyError("Es fehlen Zugangsdaten in ~/.hermes/.env: " + ", ".join(missing))
        if running_call():
            raise policy.PolicyError("Es läuft schon ein Anruf; bitte warten, bis er vorbei ist.")
        policy.check_limits(CALLS)
    except policy.PolicyError as exc:
        return out({"ok": False, "error": str(exc)}, 1)
    call_id = datetime.now().strftime("%Y%m%d-%H%M%S-") + os.urandom(2).hex()
    record = {
        "id": call_id, "to": e164, "dial": policy.dial_string(e164, env("PHONE_DIAL_FORMAT", "national")),
        "callee": (args.callee or "").strip()[:120], "task": task,
        "minutes": policy.clamp_minutes(args.minutes), "status": "queued", "created_at": now_iso(),
    }
    save(record)
    with open(CALLS / f"{call_id}.log", "ab") as logfile:
        subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "run", "--id", call_id],
                         stdin=subprocess.DEVNULL, stdout=logfile, stderr=subprocess.STDOUT,
                         start_new_session=True, close_fds=True)
    return out({"ok": True, "call_id": call_id, "to": e164, "callee": record["callee"],
                "message": "Der Anruf startet jetzt im Hintergrund. Das Ergebnis kommt als Meldung in die App."})


def cmd_run(args) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    record = load(args.id)
    if record.get("status") != "queued":
        return out({"ok": False, "error": "Dieser Anruf wurde schon gestartet."}, 1)
    record = asyncio.run(PhoneCall(record, account(), env("OPENAI_API_KEY")).run())
    notify(record)
    return out({"ok": record.get("status") == "done", "call_id": record["id"], "status": record["status"]})


def cmd_status(args) -> int:
    try:
        record = load(args.id) if args.id else latest()
    except (OSError, ValueError, policy.PolicyError):
        record = None
    if record is None:
        return out({"ok": False, "error": "Keinen solchen Anruf gefunden."}, 1)
    if record.get("status") in ACTIVE and policy.stale(record.get("created_at", ""), record.get("minutes", 15)):
        record["status"] = "failed"
        record.setdefault("error", "Der Anrufprozess ist abgebrochen.")
    return out({"ok": True, **record})


async def _check_sip() -> str:
    phone = SipPhone(account(), lambda _: None)
    try:
        await phone.open()
        await phone.register(expires=60)
        return "ok"
    except CallFailed as exc:
        return exc.reason
    finally:
        await phone.close()


async def _check_openai() -> str:
    """Opens a session and asks for one word of text: proves key, model and credit."""
    import websockets

    model = env("PHONE_REALTIME_MODEL", "gpt-realtime-2.1")
    try:
        async with websockets.connect(f"{REALTIME_URL}?model={model}", open_timeout=15,
                                      happy_eyeballs_delay=HAPPY_EYEBALLS,
                                      additional_headers={"Authorization": f"Bearer {env('OPENAI_API_KEY')}"}) as ws:
            await ws.send(json.dumps({"type": "session.update", "session": {
                "type": "realtime", "model": model, "output_modalities": ["text"]}}))
            await ws.send(json.dumps({"type": "response.create", "response": {
                "instructions": "Antworte nur mit dem Wort: bereit", "max_output_tokens": 64}}))
            while True:
                event = json.loads(await asyncio.wait_for(ws.recv(), 30))
                if event.get("type") == "error":
                    return f"Fehler: {(event.get('error') or {}).get('code')}"
                if event.get("type") == "response.done":
                    status = (event.get("response") or {}).get("status")
                    details = (event.get("response") or {}).get("status_details") or {}
                    # A reply cut at the token cap still proves key, model and credit.
                    if status == "completed" or details.get("reason") == "max_output_tokens":
                        return "ok"
                    return f"Antwort {status}: {details.get('error') or details}"
    except Exception as exc:
        return f"Verbindung fehlgeschlagen: {type(exc).__name__}"


def cmd_check(args) -> int:
    both = not (args.sip or args.openai)
    result: dict = {"missing": missing_credentials()}
    if both or args.sip:
        result["fairytel"] = asyncio.run(_check_sip()) if env("FAIRYTEL_SIP_USER") else "Zugangsdaten fehlen"
    if both or args.openai:
        result["openai"] = asyncio.run(_check_openai()) if env("OPENAI_API_KEY") else "Key fehlt"
    ok = not result["missing"] and all(result.get(k, "ok") == "ok" for k in ("fairytel", "openai"))
    return out({"ok": ok, **result}, 0 if ok else 1)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    start = sub.add_parser("start")
    start.add_argument("--to", required=True)
    start.add_argument("--callee", default="")
    start.add_argument("--minutes", default=policy.DEFAULT_MINUTES)
    start.add_argument("--task-file")
    sub.add_parser("run").add_argument("--id", required=True)
    sub.add_parser("status").add_argument("--id")
    check = sub.add_parser("check")
    check.add_argument("--sip", action="store_true")
    check.add_argument("--openai", action="store_true")
    args = parser.parse_args(argv)
    return {"start": cmd_start, "run": cmd_run, "status": cmd_status, "check": cmd_check}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
