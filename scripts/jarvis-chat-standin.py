#!/usr/bin/env python3
"""Stand in for the user in one chat for a while, and keep them posted.

A stand-in is the bounded, explicit version of "answer this for me": for a set
stretch of time JARVIS replies to one named contact itself and reports back on
what is happening. launchd owns the clock, so it survives the app being closed,
a restart and sleep.

    jarvis-chat-standin.py offer 4917648090349
    jarvis-chat-standin.py start 4917648090349 --name "Marie" --for 2h --announce
    jarvis-chat-standin.py note 4917648090349 --gist "fragt nach Samstag"
    jarvis-chat-standin.py status
    jarvis-chat-standin.py stop 4917648090349

Two people have to agree to a stand-in, and the code enforces both.

The user decides *that* it happens: `start` switches WhatsApp receiving on for
that contact, which is JARVIS writing to a real person unprompted.

The other person is told, or deliberately is not: `--announce` sends them one
fixed line first — that they are talking to an assistant and until when. There
is no default. `start` refuses to run without `--announce` or `--no-announce`,
because a default is exactly how "did you ask?" turns into "I assumed". If the
announcement cannot be delivered the stand-in does not begin at all: promising
transparency and then quietly not delivering it is worse than not offering.

Why the reporting is paced here and the *content* comes from JARVIS: the
WhatsApp bridge log carries redacted ids and body lengths, never bodies, and
its message queue is drained by the Hermes gateway — a second reader would
steal messages from it. So JARVIS drops a one-line gist after each answer, and
this script owns the thing a language model is bad at: deciding when enough has
piled up to be worth interrupting a person for. That pacing follows the chat. A
quiet one goes through almost at once, because one message an hour is not spam.
A lively one is batched, because five notifications in five minutes is what
makes people switch notifications off.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HOME = Path.home()
STATE_PATH = Path(os.environ.get("JARVIS_STANDIN_STATE",
                                HOME / ".hermes/jarvis-chat-standin.json"))
NOTIFY_URL = os.environ.get("JARVIS_NOTIFY_URL", "http://127.0.0.1:8770/notify")
SAY_URL = os.environ.get("JARVIS_SAY_URL", "http://127.0.0.1:8765/api/say")
SEND_URL = os.environ.get("JARVIS_WA_SEND_URL", "http://127.0.0.1:3000/send")
MODE_SCRIPT = Path(__file__).with_name("jarvis-whatsapp-mode.py")
MODE_STATE_PATH = Path(os.environ.get("JARVIS_WA_MODE_STATE",
                                      HOME / ".hermes/jarvis-whatsapp-mode.json"))
OWNER = os.environ.get("JARVIS_OWNER_NAME", "Marlon")
WA_CREDS = Path(os.environ.get("JARVIS_WA_CREDS",
                               HOME / ".hermes/whatsapp/session/creds.json"))
ENV_PATH = Path(os.environ.get("JARVIS_HERMES_ENV", HOME / ".hermes/.env"))

# Long enough to be useful, short enough that a forgotten stand-in is not a
# standing licence to talk to someone for a week.
DEFAULT_HOURS = 2.0
MAX_HOURS = 8.0
# Gists are one line each; past this a report is a wall of text nobody reads.
MAX_GIST_LINES = 8
# The whole run, kept for the interface to show when the user opens a stand-in.
# Long enough to be the conversation, short enough that the state file stays a
# state file.
MAX_HISTORY = 60
# How far back the traffic estimate looks. Shorter and a lull looks like the end
# of the conversation; longer and a burst throttles long after it is over.
RATE_WINDOW_SECONDS = 30 * 60
# Suggesting a stand-in twice in one afternoon is nagging, and the answer to
# nagging is that people stop reading the suggestion at all.
OFFER_COOLDOWN_SECONDS = 12 * 3600


# ------------------------------------------------------------------- helpers

def parse_duration(text: str) -> float:
    """'2h', '90m', '1.5h' -> hours. Raises ValueError on anything else."""
    match = re.fullmatch(r"\s*(\d+(?:[.,]\d+)?)\s*([hm])\s*", str(text or ""), re.I)
    if not match:
        raise ValueError(f"Dauer nicht verstanden: {text!r} — erwartet z. B. 2h oder 90m")
    amount = float(match.group(1).replace(",", "."))
    hours = amount if match.group(2).lower() == "h" else amount / 60
    if not 0 < hours <= MAX_HOURS:
        raise ValueError(f"Dauer muss zwischen 0 und {MAX_HOURS:g} Stunden liegen, nicht {hours:g}")
    return hours


def bare(contact: str) -> str:
    """4917648090349@s.whatsapp.net -> 4917648090349."""
    return str(contact or "").strip().split("@", 1)[0].split(":", 1)[0].lstrip("+")


def chat_id(key: str) -> str:
    return f"{key}@s.whatsapp.net"


def human_duration(hours: float) -> str:
    if hours < 1:
        return f"{round(hours * 60)} Minuten"
    if abs(hours - 1) < 0.01:
        return "eine Stunde"
    return f"{hours:g} Stunden".replace(".", ",")


def load() -> dict:
    try:
        data = json.loads(STATE_PATH.read_text())
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    if not isinstance(data.get("standins"), dict):
        data["standins"] = {}
    if not isinstance(data.get("offers"), dict):
        data["offers"] = {}
    return data


def save(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2))
    os.chmod(tmp, 0o600)   # contact numbers and gists are personal data
    tmp.replace(STATE_PATH)


def env_token(*names: str) -> str:
    """Tokens live in ~/.hermes/.env, never in the launchd plist.

    A plist is world-readable; the env file is 600.
    """
    for name in names:
        value = os.environ.get(name, "")
        if value:
            return value
    try:
        found: dict[str, str] = {}
        for line in ENV_PATH.read_text().splitlines():
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip().strip("'\"")
            if key in names and value:
                found.setdefault(key, value)
        for name in names:
            if name in found:
                return found[name]
    except OSError:
        pass
    return ""


def post_json(url: str, payload: dict, headers: dict | None = None) -> bool:
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return 200 <= response.status < 300
    except (urllib.error.URLError, OSError, ValueError):
        return False


def system_banner(text: str) -> None:
    """Backstop for the one case that matters: the bridge being down."""
    try:
        subprocess.run(["osascript", "-e",
                        f'display notification {json.dumps(text)} with title "JARVIS"'],
                       check=False, capture_output=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        pass


def deliver(title: str, text: str, speak: bool) -> None:
    """The app is where JARVIS lives, so that is where a report belongs."""
    delivered = post_json(NOTIFY_URL, {"kind": "chat_standin", "title": title, "text": text},
                          {"Authorization": f"Bearer {env_token('JARVIS_APP_TOKEN', 'JARVIS_HUD_TOKEN')}"})
    if not delivered:
        system_banner(f"{title}: {text}")
    if speak:
        post_json(SAY_URL, {"text": f"{title}. {text}", "priority": "normal"},
                  {"X-Jarvis-Token": env_token("JARVIS_HUD_TOKEN", "JARVIS_APP_TOKEN")})


# -------------------------------------------------------------- the announcement

def opening_line(hours: float) -> str:
    """Fixed wording, on purpose.

    A disclosure that a model rewrites each time is a disclosure that can be
    softened until it no longer discloses anything.
    """
    return (f"Kurz vorweg: {OWNER} ist gerade nicht selbst am Handy. "
            f"Für etwa {human_duration(hours)} antwortet hier sein KI-Assistent. "
            f"{OWNER} liest alles später nach.")


def closing_line() -> str:
    return f"{OWNER} ist wieder selbst da — der Assistent ist raus."


def tell_contact(key: str, text: str) -> bool:
    return post_json(SEND_URL, {"chatId": chat_id(key), "message": text})


# ---------------------------------------------------------------- the pacing

def report_interval(standin: dict, now: float) -> float:
    """How long to sit on a report, given how fast this chat is moving.

    Not a fixed number, because "every 20 minutes" is wrong twice: too slow for
    a chat where one message arrives an hour, too noisy for one where five
    arrive a minute.
    """
    recent = [t for t in standin.get("inbound", []) if now - t <= RATE_WINDOW_SECONDS]
    if len(recent) <= 1:
        return 120.0        # quiet: essentially straight through
    if len(recent) <= 4:
        return 480.0        # a conversation: gather a few turns first
    return 1200.0           # lively: one digest, not a running commentary


def report_due(standin: dict, now: float) -> bool:
    pending = standin.get("pending", [])
    if not pending:
        return False
    if any(item.get("urgent") for item in pending):
        return True         # JARVIS is stuck; waiting helps nobody
    return now - standin.get("last_report", standin.get("started", now)) >= report_interval(standin, now)


def summarise(standin: dict) -> str:
    lines = [item["gist"] for item in standin.get("pending", []) if item.get("gist")]
    if not lines:
        return "nichts Neues"
    shown = lines[:MAX_GIST_LINES]
    text = " · ".join(shown)
    if len(lines) > len(shown):
        text += f" · (+{len(lines) - len(shown)} weitere)"
    return text


def flush(state: dict, key: str, standin: dict, now: float, speak: bool,
          closing: str = "") -> None:
    text = summarise(standin)
    if closing:
        text = f"{text} — {closing}" if standin.get("pending") else closing
    deliver(standin.get("name") or key, text, speak)
    standin["pending"] = []
    standin["last_report"] = now
    standin["reported"] = int(standin.get("reported", 0)) + 1


# ------------------------------------------------------------------ commands

def owner_ids() -> set[str]:
    """The user's own WhatsApp identities — their number and their LID.

    These belong on the allowlist whatever else is on it: they are how the user
    talks to JARVIS over WhatsApp in the first place. Setting the list to
    exactly the stand-ins would drop them and kill that chat, which looks like
    JARVIS having gone deaf rather than like a permission change.
    """
    try:
        me = json.loads(WA_CREDS.read_text()).get("me", {})
    except (OSError, ValueError, AttributeError):
        return set()
    return {bare(value) for value in (me.get("id"), me.get("lid")) if value}


def switch_receiving_on(contacts: list[str], hours: float) -> bool:
    """Set receiving to exactly these contacts for this long.

    `--exclusive`, never a union: the allowlist has to *equal* the running
    stand-ins. Without it a contact stayed on the list after their own
    stand-in ended — still answered automatically, but with no stand-in behind
    it, so no reporting, no announcement and no end of its own.
    """
    argv = [sys.executable, str(MODE_SCRIPT), "on", "--exclusive", "--for", f"{hours:g}h"]
    for contact in sorted(set(contacts) | owner_ids()):
        argv += ["--contact", contact]
    result = subprocess.run(argv, check=False, capture_output=True, text=True, timeout=130)
    if result.returncode != 0:
        print(result.stderr.strip() or "Empfangen konnte nicht eingeschaltet werden.",
              file=sys.stderr)
        return False
    return True


def mode_expiry() -> float:
    try:
        return float(json.loads(MODE_STATE_PATH.read_text()).get("until") or 0)
    except (OSError, ValueError, TypeError, AttributeError):
        return 0.0


def active_keys(state: dict) -> set:
    """The stand-ins that may answer — which is every one that still exists.

    There is deliberately no paused state: the one event that would have caused
    one, the user writing in that chat, ends the stand-in outright.
    """
    return set(state.get("standins", {}))


def mode_is_bot() -> bool:
    try:
        return any(line.strip() == "WHATSAPP_MODE=bot"
                   for line in ENV_PATH.read_text().splitlines())
    except OSError:
        return False


def longest_until(state: dict) -> float:
    active = active_keys(state)
    return max((s.get("until", 0) for k, s in state.get("standins", {}).items() if k in active),
               default=0.0)


def allowlist() -> set[str]:
    try:
        line = next(l for l in ENV_PATH.read_text().splitlines()
                    if l.startswith("WHATSAPP_ALLOWED_USERS="))
    except (OSError, StopIteration):
        return set()
    value = line.partition("=")[2].strip().strip("'\"")
    return {v.strip() for v in value.split(",") if v.strip()}


def ensure_mode_matches(state: dict, now: float) -> None:
    """Receiving must mirror the running stand-ins: who, and for how long.

    Two ways it drifted. The window: `jarvis-whatsapp-mode.py` has one global
    timer, so a short stand-in started after a long one pulled the expiry
    *inwards* and would have made an announced stand-in go deaf mid-chat.
    Whoever needs it longest sets the window.

    And the list: `on` unions by default, so a contact stayed allow-listed
    after their own stand-in had ended — answered automatically for hours with
    nothing behind it. The list is now set, not extended.
    """
    running = active_keys(state)
    if not running:
        # Nothing left to stand in for: nobody should be received from.
        receiving_off_if_last(state)
        return
    wanted = running | owner_ids()
    longest = longest_until(state)
    # Slack on the clock, because switching the mode restarts the gateway: that
    # belongs where the window is genuinely short, not on every poll tick.
    if allowlist() == wanted and mode_expiry() >= longest - 120:
        return
    switch_receiving_on(sorted(running), (longest - now) / 3600)


def receiving_off_if_last(state: dict) -> None:
    """Only close the receive session when no stand-in still needs it.

    `off` is global — it restores every managed key. Calling it while a second
    stand-in is running would silently make that one deaf.
    """
    if active_keys(state):
        return
    if not mode_is_bot():
        return   # already off; switching again would restart the gateway for nothing
    try:
        subprocess.run([sys.executable, str(MODE_SCRIPT), "off"],
                       check=False, capture_output=True, timeout=130)
    except (OSError, subprocess.SubprocessError):
        pass  # mode.py's own expiry job remains the backstop.


def finish(state: dict, key: str, standin: dict, now: float, closing: str) -> None:
    """End one stand-in: tell the contact if it was announced, then report."""
    if standin.get("announced"):
        tell_contact(key, closing_line())
    flush(state, key, standin, now, speak=True, closing=closing)
    state["standins"].pop(key, None)


def cmd_offer(args: argparse.Namespace) -> int:
    """Should JARVIS suggest a stand-in for this chat right now?

    Exit 0 means yes and records it, 1 means no. Keeping the anti-nagging rule
    here rather than in the prompt is the difference between a rule and a hope.
    """
    key = bare(args.contact)
    now = time.time()
    state = load()
    if key in state["standins"]:
        print("Läuft bereits.")
        return 1
    last = float(state["offers"].get(key, 0))
    if now - last < OFFER_COOLDOWN_SECONDS:
        hours = (OFFER_COOLDOWN_SECONDS - (now - last)) / 3600
        print(f"Schon vorgeschlagen, wieder in {hours:.0f}h.")
        return 1
    state["offers"][key] = now
    save(state)
    print("Vorschlagen: ja.")
    return 0


def cmd_start(args: argparse.Namespace) -> int:
    key = bare(args.contact)
    if not key or not key.isdigit():
        print("Eine Vertretung braucht genau eine Nummer, keine Platzhalter.", file=sys.stderr)
        return 2
    hours = parse_duration(args.duration)
    now = time.time()
    state = load()
    if key in state["standins"]:
        print(f"Für {key} läuft bereits eine Vertretung.", file=sys.stderr)
        return 1

    # Receiving first: it is internal and reversible, and the contact must not
    # see an announcement for something that then fails to start.
    #
    # Ask for the longest window anyone still needs, not just this one's: the
    # mode timer is global, so a short request here would cut an already
    # running stand-in short.
    window = max(hours, (longest_until(state) - now) / 3600)
    if not switch_receiving_on(sorted(set(state["standins"]) | {key}), window):
        return 1

    if args.announce and not tell_contact(key, opening_line(hours)):
        receiving_off_if_last(state)
        print("Die Ansage an den Kontakt ging nicht raus — Vertretung nicht gestartet.",
              file=sys.stderr)
        return 1

    state["standins"][key] = {
        "name": args.name or key,
        "started": now,
        "until": now + hours * 3600,
        "announced": bool(args.announce),
        "pending": [],
        "history": [],
        "inbound": [],
        "exchanges": 0,
        "last_report": now,
        "reported": 0,
    }
    save(state)
    until = time.strftime("%H:%M", time.localtime(now + hours * 3600))
    told = "Kontakt ist informiert" if args.announce else "Kontakt weiß nichts davon"
    print(f"Vertretung läuft: {state['standins'][key]['name']} bis {until} "
          f"({human_duration(hours)}). {told}.")
    return 0


def cmd_takeover(args: argparse.Namespace) -> int:
    """The user started writing in that chat themselves: the stand-in is over.

    It does not ask. Asking was tried and was wrong: by the time a question
    reaches the user they are already several messages in, and every one of
    those is a second voice in a conversation they have taken back. There is no
    reading of "I am typing here myself" under which JARVIS should carry on, so
    there is nothing to ask about.
    """
    key = bare(args.contact)
    now = time.time()
    state = load()
    standin = state["standins"].get(key)
    if standin is None:
        print(f"Keine laufende Vertretung für {key}.", file=sys.stderr)
        return 1
    finish(state, key, standin, now, "Vertretung beendet — du schreibst selbst.")
    save(state)
    ensure_mode_matches(state, now)
    print(f"Vertretung für {standin.get('name') or key} beendet, weil du selbst schreibst.")
    return 0


def cmd_note(args: argparse.Namespace) -> int:
    key = bare(args.contact)
    now = time.time()
    state = load()
    standin = state["standins"].get(key)
    if standin is None:
        print(f"Keine laufende Vertretung für {key}.", file=sys.stderr)
        return 1
    entry = {"at": now, "gist": (args.gist or "").strip(), "urgent": bool(args.urgent)}
    standin.setdefault("pending", []).append(entry)
    # `pending` is emptied on every report, so it cannot answer "what has
    # happened so far". This can: it is what the interface shows when the user
    # opens a running stand-in.
    standin["history"] = (standin.get("history") or [])[-(MAX_HISTORY - 1):] + [entry]
    standin["exchanges"] = int(standin.get("exchanges", 0)) + 1
    inbound = [t for t in standin.setdefault("inbound", []) if now - t <= RATE_WINDOW_SECONDS]
    inbound.append(now)
    standin["inbound"] = inbound
    # Report straight away when it is due, rather than making the user wait for
    # the next poll tick on top of the interval they already waited for.
    if report_due(standin, now):
        flush(state, key, standin, now, speak=not args.quiet)
    save(state)
    return 0


def cmd_poll(_args: argparse.Namespace) -> int:
    now = time.time()
    state = load()
    changed = False
    for key, standin in list(state["standins"].items()):
        if now >= standin.get("until", 0):
            finish(state, key, standin, now,
                   f"Vertretung beendet ({standin.get('reported', 0)} Meldungen).")
            changed = True
            continue
        if report_due(standin, now):
            flush(state, key, standin, now, speak=True)
            changed = True
    if changed:
        save(state)
    ensure_mode_matches(state, now)
    return 0


def cmd_status(_args: argparse.Namespace) -> int:
    state = load()
    if not state["standins"]:
        print("Keine laufende Vertretung.")
        return 0
    now = time.time()
    for key, standin in state["standins"].items():
        left = max(0, standin.get("until", 0) - now) / 60
        told = "angesagt" if standin.get("announced") else "nicht angesagt"
        print(f"{standin.get('name') or key} ({key}) — noch {left:.0f} Min, {told}, "
              f"{standin.get('exchanges', 0)} Nachrichten, "
              f"{len(standin.get('pending', []))} ungemeldet, "
              f"Takt {report_interval(standin, now) / 60:.0f} Min")
    return 0


def cmd_stop(args: argparse.Namespace) -> int:
    key = bare(args.contact)
    state = load()
    standin = state["standins"].get(key)
    if standin is None:
        print(f"Keine laufende Vertretung für {key}.", file=sys.stderr)
        return 1
    now = time.time()
    finish(state, key, standin, now, "Vertretung beendet.")
    save(state)
    # Do not wait for the next poll tick: until the list is re-set, this
    # contact is still being answered automatically with nothing behind it.
    ensure_mode_matches(state, now)
    print(f"Vertretung für {standin.get('name') or key} beendet.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    offer = sub.add_parser("offer", help="darf eine Vertretung vorgeschlagen werden?")
    offer.add_argument("contact")
    offer.set_defaults(func=cmd_offer)

    start = sub.add_parser("start", help="Vertretung für einen Kontakt beginnen")
    start.add_argument("contact")
    start.add_argument("--name", default="")
    start.add_argument("--for", dest="duration", default=f"{DEFAULT_HOURS:g}h")
    told = start.add_mutually_exclusive_group(required=True)
    told.add_argument("--announce", action="store_true",
                      help="dem Kontakt einmalig sagen, dass hier ein Assistent antwortet")
    told.add_argument("--no-announce", dest="announce", action="store_false",
                      help="ohne Ansage — der Kontakt erfährt es nicht")
    start.set_defaults(func=cmd_start)

    takeover = sub.add_parser("takeover",
                              help="der User schreibt selbst — Vertretung sofort beenden")
    takeover.add_argument("contact")
    takeover.set_defaults(func=cmd_takeover)

    note = sub.add_parser("note", help="eine Zeile zum laufenden Chat festhalten")
    note.add_argument("contact")
    note.add_argument("--gist", required=True)
    note.add_argument("--urgent", action="store_true",
                      help="sofort melden — JARVIS kommt nicht weiter")
    note.add_argument("--quiet", action="store_true", help="nicht vorlesen")
    note.set_defaults(func=cmd_note)

    sub.add_parser("poll", help="von launchd aufgerufen").set_defaults(func=cmd_poll)
    sub.add_parser("status", help="laufende Vertretungen zeigen").set_defaults(func=cmd_status)

    stop = sub.add_parser("stop", help="Vertretung vorzeitig beenden")
    stop.add_argument("contact")
    stop.set_defaults(func=cmd_stop)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
