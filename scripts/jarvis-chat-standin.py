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
import contextlib
import fcntl
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
NOTIFY_KIND = "task"
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

# Where the gateway records what it received and sent. It is the only place a
# stand-in can read the conversation from: the WhatsApp bridge log carries
# redacted ids and body lengths, and its message queue is drained by the
# gateway itself, so a second reader there would steal messages.
GATEWAY_LOG = Path(os.environ.get("JARVIS_GATEWAY_LOG",
                                  HOME / ".hermes/logs/gateway.log"))
# The WhatsApp bridge prints its mode and allowlist when it starts. That is the
# only proof a stand-in has that the contact can actually be heard.
BRIDGE_LOG = Path(os.environ.get("JARVIS_WA_BRIDGE_LOG",
                                 HOME / ".hermes/whatsapp/bridge.log"))
# How long a stand-in may wait for receiving to come up before it is called off.
# Switching receiving on is a full gateway restart, and under load that has
# taken five minutes.
LIVE_WAIT_SECONDS = 15 * 60
SESSION_DIR = Path(os.environ.get("JARVIS_WA_SESSION",
                                  HOME / ".hermes/whatsapp/session"))
GATEWAY_LABEL = os.environ.get("JARVIS_GATEWAY_LABEL", "ai.hermes.gateway")
# The port the JARVIS app reaches Hermes on.
API_PORT = int(os.environ.get("JARVIS_HERMES_API_PORT", "8642"))
# One inbound message quoted back to the user, cut to a readable line. The
# gateway already truncates at 80, so this is a second belt, not the trousers.
MAX_GIST_CHARS = 90
# The gateway forwards the owner's own messages in a stand-in chat with this
# prefix. They are his, not the contact's: they must never be counted as an
# exchange, reported back to him, or spoken aloud.
OWNER_PREFIX = "[owner reply]"
# A single poll must not pull an unbounded log into memory.
MAX_LOG_READ = 2 * 1024 * 1024
# How long the whole system waits before asking launchd for another gateway
# restart, and how many times in a row it may ask before giving up. Without
# both, a permanently broken API turns the poller into a restart loop that
# interrupts a live conversation once a minute.
RESTART_COOLDOWN_SECONDS = 300.0
MAX_RESTART_ATTEMPTS = 3
# Giving up has to expire too. Three failures mean this minute's problem is
# not one a restart solves, not that the machine may never be repaired again —
# without this an outage that becomes fixable later stays broken until someone
# notices by hand.
RESTART_GIVEUP_SECONDS = 3600.0
RESTART_STAMP = Path(os.environ.get("JARVIS_RESTART_STAMP",
                                    HOME / ".hermes/jarvis-gateway-restart.stamp"))


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


def aliases(key: str) -> set[str]:
    """Every id this contact can appear under.

    An inbound chat is reported as a LID (`1332…@lid`) while the number a
    stand-in was started from is a phone JID. Without walking the session's
    mapping files the two never match, and a stand-in that is answering
    perfectly looks asleep.
    """
    found: set[str] = set()
    queue = [bare(key)]
    while queue:
        current = queue.pop()
        if not current or current in found:
            continue
        found.add(current)
        for suffix in ("", "_reverse"):
            try:
                mapped = bare(json.loads(
                    (SESSION_DIR / f"lid-mapping-{current}{suffix}.json").read_text()))
            except (OSError, ValueError):
                continue
            if mapped and mapped not in found:
                queue.append(mapped)
    return found


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


@contextlib.contextmanager
def state_lock(blocking: bool = True):
    """Hold the state file across a whole load-modify-save.

    `poll` now does real work between reading and writing, and `stop`,
    `takeover` and `note` can run at any moment from the agent. Without a lock
    a poll that started before a `stop` writes its older snapshot afterwards
    and resurrects a stand-in the user just ended — which means JARVIS goes on
    answering someone in his name after he told it to stop.
    """
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    handle = STATE_PATH.with_suffix(".lock").open("a+")
    try:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX if blocking
                        else fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            # Only `poll` asks without blocking. Starting a stand-in holds the
            # lock while it waits for the gateway, and a minute-by-minute poll
            # queueing up behind that would pile ticks on top of each other.
            # Skipping is free: the next tick is sixty seconds away.
            yield False
            return
        yield True
    finally:
        with contextlib.suppress(OSError):
            fcntl.flock(handle, fcntl.LOCK_UN)
        handle.close()


def save(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    # Per-process name: two writers must not share one temporary file.
    tmp = STATE_PATH.with_suffix(f".{os.getpid()}.tmp")
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


def deliver(title: str, text: str, speak: bool, spoken: str = "") -> None:
    """The app is where JARVIS lives, so that is where a report belongs.

    `spoken` exists because the two channels do not deserve the same content.
    The app is a screen the user chose to look at; the speaker and the lock
    screen are a room other people are in.
    """
    # "task", not a kind of its own: the bridge accepts only NOTIFY_KINDS and
    # answered "chat_standin" with 400, so no report ever reached the app — the
    # user got at most a banner. A stand-in is a standing task there anyway.
    delivered = post_json(NOTIFY_URL, {"kind": NOTIFY_KIND, "title": title, "text": text},
                          {"Authorization": f"Bearer {env_token('JARVIS_APP_TOKEN', 'JARVIS_HUD_TOKEN')}"})
    if not delivered:
        system_banner(f"{title}: {spoken or text}")
    if speak:
        post_json(SAY_URL, {"text": f"{title}. {spoken or text}", "priority": "normal"},
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


def spoken_form(standin: dict, shown: str, closing: str) -> str:
    """What may be said out loud, which is not always what may be shown.

    A gist JARVIS wrote is its own summary and safe to speak. A line read out
    of the gateway log is the other person's message, verbatim — a diagnosis,
    an address, a one-time code. That belongs on the screen the user chose to
    look at, never on a speaker or a lock screen banner. So a report built
    from log lines is announced by its count, and the words stay in the app.
    """
    pending = standin.get("pending") or []
    if not any(item.get("src") == "log" for item in pending):
        return shown          # JARVIS's own words, or a closing line: speak it
    count = len(pending)
    news = "eine neue Nachricht" if count == 1 else f"{count} neue Nachrichten"
    return f"{news} — {closing}" if closing else news


def flush(state: dict, key: str, standin: dict, now: float, speak: bool,
          closing: str = "") -> None:
    text = summarise(standin)
    if closing:
        text = f"{text} — {closing}" if standin.get("pending") else closing
    # After `text` is final: a stand-in that ends with nothing pending must
    # still announce that it ended, not summarise an empty list.
    spoken = spoken_form(standin, text, closing)
    deliver(standin.get("name") or key, text, speak, spoken=spoken)
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


def bridge_log_size() -> int:
    try:
        return BRIDGE_LOG.stat().st_size
    except OSError:
        return 0


def receiving_live(key: str, offset: int) -> bool:
    """Has a bot-mode bridge with this contact on its list connected since `offset`?

    Switching receiving on only writes the env and asks for a gateway restart.
    Until a new bridge has started in bot mode and connected, the contact's
    messages are dropped, so "Vertretung läuft" before that is a promise nobody
    keeps. On 2026-09-14 a whole test stand-in passed that way. The bridge log
    carries no timestamps, so only what was written after the stand-in started
    counts. Every switch starts a fresh bridge (the mode script stops the old
    one), so a matching header is always there to find.
    """
    try:
        size = BRIDGE_LOG.stat().st_size
        with BRIDGE_LOG.open("rb") as handle:
            handle.seek(offset if 0 <= offset <= size else 0)
            chunk = handle.read(MAX_LOG_READ).decode("utf-8", "replace")
    except OSError:
        return False
    bot = listed = live = False
    for line in chunk.splitlines():
        if "bridge listening on port" in line:
            bot, listed, live = "(mode: bot)" in line, False, False
        elif "Allowed users:" in line:
            listed = bot and key in re.findall(r"\d+", line)
        elif "WhatsApp connected!" in line:
            live = bot and listed
    return live


def activate_pending(state: dict, now: float) -> bool:
    """Make a stand-in that is being set up live once it can hear, or call it off.

    The announcement belongs here, not in `start`: telling someone an assistant
    answers while their messages are still dropped is worse than no stand-in.
    If it cannot be delivered, the stand-in does not begin, same rule as before.
    """
    changed = False
    for key, standin in list(state["standins"].items()):
        if standin.get("live", True):
            continue
        name = standin.get("name") or key
        if receiving_live(key, int(standin.get("bridge_offset") or 0)):
            hours = float(standin.get("hours") or 0) or max(0.0, standin.get("until", now) - now) / 3600
            if standin.get("announce") and not tell_contact(key, opening_line(hours)):
                del state["standins"][key]
                deliver(name, "Die Ansage an den Kontakt ging nicht raus. Vertretung nicht gestartet.",
                        speak=True)
                changed = True
                continue
            standin.update(live=True, announced=bool(standin.get("announce")), last_report=now)
            until = time.strftime("%H:%M", time.localtime(standin.get("until", now)))
            told = "Kontakt ist informiert" if standin["announced"] else "Kontakt weiß nichts davon"
            deliver(name, f"Vertretung läuft jetzt, bis {until}. {told}.", speak=True)
            changed = True
        elif now - standin.get("started", now) >= LIVE_WAIT_SECONDS:
            del state["standins"][key]
            deliver(name, "Der WhatsApp-Empfang kam nicht zustande. Vertretung abgebrochen.",
                    speak=True)
            changed = True
    return changed


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
    # Before the switch: the new bridge's startup lines land after this point.
    offset = bridge_log_size()
    if not switch_receiving_on(sorted(set(state["standins"]) | {key}), window):
        return 1

    # Not live yet, and not announced yet: the switch only asked for a gateway
    # restart, which waits for this very turn to finish and can take minutes.
    # The poller announces and reports once a bridge can really hear the
    # contact (`activate_pending`).
    state["standins"][key] = {
        "name": args.name or key,
        "started": now,
        "until": now + hours * 3600,
        "hours": hours,
        "announce": bool(args.announce),
        "announced": False,
        "live": False,
        "bridge_offset": offset,
        "pending": [],
        "history": [],
        "inbound": [],
        "exchanges": 0,
        "last_report": now,
        "reported": 0,
    }
    save(state)
    told = ("Die Ansage an den Kontakt geht erst raus, wenn der Empfang steht."
            if args.announce else "Der Kontakt erfährt nichts davon.")
    print(f"Vertretung für {state['standins'][key]['name']} wird eingerichtet "
          f"({human_duration(hours)}). Der WhatsApp-Empfang startet dafür neu, meist "
          f"in ein bis zwei Minuten, unter Last länger. {told} Sobald sie wirklich "
          f"läuft, kommt eine Meldung in die App. Bis dahin nicht als laufend ansagen.")
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


# The gateway logs the body with %r, so the quote character depends on the
# message: repr("Wie geht's?") comes out double-quoted. Matching only `msg='`
# silently dropped every German message containing an apostrophe — "geht's",
# "gibt's", "hab's" — which is most of them. The backreference accepts either
# quote. `user=.*?` is non-greedy because a WhatsApp push name contains spaces
# ("Marlon Spallek").
#
# The body is greedy and the tail is spelled out to the end of the record.
# Greedy alone would stop at any ` reply_to_id=` the sender typed into their
# own message; requiring `reply_to_id=<token> reply_to_text=` after it means
# the split has to line up with the record the gateway actually wrote, and the
# real terminator — being last — is the one greedy prefers.
INBOUND_RE = re.compile(
    r"^(?P<ts>\d{4}-\d\d-\d\d \d\d:\d\d:\d\d),(?P<ms>\d{1,6}) .*?"
    r"inbound message: platform=whatsapp user=.*? chat=(?P<chat>\S+) "
    r"msg=(?P<q>[\'\"])(?P<msg>.*)(?P=q) reply_to_id=\S+ reply_to_text=")
# A chat id is digits and a known domain. The push name is logged unsanitised,
# so a contact who can get a newline into theirs could in principle write a
# second line that reads like a record of its own. It would still have to name
# a chat that belongs to a running stand-in, and this keeps anything that is
# not shaped like a WhatsApp id out of that comparison entirely.
CHAT_ID_RE = re.compile(r"^\d{5,20}@(?:s\.whatsapp\.net|lid)$")


def log_time(text: str, millis: str = "0") -> float:
    """Local log stamp to epoch, milliseconds kept.

    The milliseconds matter twice: a message that arrives in the same second a
    stand-in starts must not be read as older than it, and two identical
    replies seconds apart must stay two events.
    """
    try:
        base = time.mktime(time.strptime(text, "%Y-%m-%d %H:%M:%S"))
    except (ValueError, OverflowError):
        return 0.0
    return base + int((millis or "0")[:3].ljust(3, "0")) / 1000.0


def scan_gateway_log(state: dict, now: float) -> bool:
    """Turn what the gateway actually received into stand-in notes.

    The design left the gist to JARVIS: it answers the message, so it knows
    what the message was about. In a WhatsApp turn it cannot say so —
    `platform_toolsets.whatsapp` grants the WhatsApp toolset and no terminal,
    so there is nothing to call `note` with. The reporting half of a stand-in
    was therefore dead while the answering half worked, and the app read "noch
    nichts passiert" straight through a live conversation. That is the worse
    of the two failures: the user stops watching a chat that is being answered
    in their name.

    So the pacing stays here and the content is read from the gateway's own
    log, which is the one place the bodies exist. `note` still works and wins:
    a gist JARVIS wrote is better than a quoted line.
    """
    if not state["standins"]:
        return False
    try:
        stat = GATEWAY_LOG.stat()
    except OSError:
        return False
    mark = state.setdefault("log", {})
    before = (mark.get("offset"), mark.get("inode"))
    # An unseen or rotated log is read from the top and filtered by each
    # stand-in's start time, so a stand-in that began before this ever ran
    # still gets its conversation instead of starting blind.
    offset = 0 if mark.get("inode") != stat.st_ino else int(mark.get("offset") or 0)
    if offset > stat.st_size:
        offset = 0
    # Never read the whole file into memory: a log that grew without anyone
    # polling is skipped forward instead.
    if stat.st_size - offset > MAX_LOG_READ:
        offset = stat.st_size - MAX_LOG_READ
    # Read bytes, not text. A decoded chunk cannot be measured back into a
    # byte offset: one undecodable byte becomes a three-byte replacement
    # character, and from then on every seek is off by the difference — the
    # scanner silently reads from the middle of lines for ever after.
    try:
        with GATEWAY_LOG.open("rb") as handle:
            handle.seek(offset)
            raw = handle.read(MAX_LOG_READ)
    except OSError:
        return False
    # The gateway may be mid-write. Stop at the last complete line and leave
    # the offset before the tail, or a half-written message is consumed,
    # fails to parse, and is lost for good. A newline byte cannot occur inside
    # a UTF-8 sequence, so this never splits a character.
    complete, newline, _tail = raw.rpartition(b"\n")
    if not newline:
        return False                     # nothing complete yet; come back later
    mark["offset"] = offset + len(complete) + 1
    mark["inode"] = stat.st_ino
    chunk = complete.decode("utf-8", "replace")

    # A stale mapping file can hand two stand-ins the same alias. Attributing
    # the message to whichever won the dict is worse than dropping it: it puts
    # one contact's words into another contact's report.
    by_alias: dict = {}
    for key in state["standins"]:
        for alias in aliases(key):
            by_alias[alias] = key if by_alias.get(alias, key) == key else None
    changed = False
    for line in chunk.splitlines():
        match = INBOUND_RE.search(line)
        if not match:
            continue
        chat = match.group("chat")
        if not CHAT_ID_RE.match(chat):
            continue        # not a shape WhatsApp writes
        key = by_alias.get(bare(chat))
        if key is None:
            continue        # not a stand-in, or an ambiguous alias
        standin = state["standins"][key]
        at = log_time(match.group("ts"), match.group("ms")) or now
        if at < standin.get("started", 0):
            continue        # older than this stand-in: not its conversation
        gist = " ".join(match.group("msg").split())[:MAX_GIST_CHARS]
        if not gist or gist.startswith(OWNER_PREFIX):
            # Known and deliberately narrow: the log carries no sender field,
            # only this prefix, so a contact who opens a message with those
            # exact words is dropped with it. Counting the user's own messages
            # as the contact's would happen in every stand-in; this costs one
            # crafted message.
            continue
        if any(item.get("gist") == gist and item.get("at") == at
               for item in standin.get("history") or []):
            continue        # the very same log line, re-read after a reset
        entry = {"at": at, "gist": gist, "urgent": False, "src": "log"}
        standin.setdefault("pending", []).append(entry)
        standin["history"] = (standin.get("history") or [])[-(MAX_HISTORY - 1):] + [entry]
        standin["exchanges"] = int(standin.get("exchanges", 0)) + 1
        inbound = [t for t in standin.setdefault("inbound", [])
                   if now - t <= RATE_WINDOW_SECONDS]
        inbound.append(at)
        standin["inbound"] = inbound
        changed = True
    return changed or (mark.get("offset"), mark.get("inode")) != before


def api_listeners() -> set:
    """The pids holding the app's Hermes port, or None when it cannot be told.

    Asked with `lsof` rather than by connecting: a poll tick must not make a
    network call, and the test suite is deliberately offline. The pids matter
    and not just a yes/no, because during the restart race the *old* listener
    still holds the port for a moment — a plain "is it bound?" would call that
    a successful restart and walk away from the exact failure it exists to
    catch.
    """
    try:
        done = subprocess.run(["lsof", "-t", "-nP", f"-iTCP:{API_PORT}", "-sTCP:LISTEN"],
                              capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return None
    output = getattr(done, "stdout", None)
    if output is None:
        return None
    return {pid for pid in output.split() if pid.isdigit()}


def api_listening() -> bool:
    """Whether the port is held at all. Unknown counts as held: doing nothing
    is the right answer whenever the failure has not actually been shown."""
    pids = api_listeners()
    return True if pids is None else bool(pids)


def gateway_service_running() -> bool:
    try:
        done = subprocess.run(["launchctl", "print",
                               f"gui/{os.getuid()}/{GATEWAY_LABEL}"],
                              capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0 and "state = running" in done.stdout


def read_restart_stamp() -> tuple:
    """(when the last restart was asked for, how many in a row) — shared file.

    Shared on purpose: the mode script and this poller can both decide a
    restart is due within the same minute, and two `kickstart -k` in a row
    kill the gateway that the first one had just brought up.
    """
    try:
        when, attempts = (RESTART_STAMP.read_text().split() + ["0"])[:2]
        return float(when), int(attempts)
    except (OSError, ValueError):
        return 0.0, 0


def note_restart_request(now: float, attempts: int) -> None:
    try:
        RESTART_STAMP.parent.mkdir(parents=True, exist_ok=True)
        RESTART_STAMP.write_text(f"{now} {attempts}")
    except OSError:
        pass


def ensure_api_up() -> None:
    """Bring the app's Hermes port back when a restart came up deaf.

    Switching receive mode restarts the gateway, and the replacement sometimes
    reaches for the API port before the old listener has let go of it. It logs
    `address already in use`, drops api_server, and runs on with WhatsApp
    only — so the stand-in keeps answering while the JARVIS app says "Hermes
    ist nicht erreichbar". Every stand-in start and stop can cause it, which
    is why something outside the gateway has to notice.

    Three guards, because a repair that runs every minute is its own outage:

    - only when the service is up but the port is not, so a gateway the user
      stopped on purpose stays stopped;
    - not within the cooldown, so this and the mode script cannot restart the
      gateway twice on top of each other;
    - and never more than MAX_RESTART_ATTEMPTS in a row, because a permanently
      misconfigured API would otherwise interrupt a live conversation once a
      minute for ever. Giving up leaves the app showing "nicht erreichbar",
      which is the honest state and a quiet one.
    """
    now = time.time()
    if api_listening():
        with contextlib.suppress(OSError):
            RESTART_STAMP.unlink()      # healthy again: forget the history
        return
    if not gateway_service_running():
        return
    when, attempts = read_restart_stamp()
    if now - when < RESTART_COOLDOWN_SECONDS:
        return
    if now - when >= RESTART_GIVEUP_SECONDS:
        attempts = 0        # a new outage, not the old one
    if attempts >= MAX_RESTART_ATTEMPTS:
        print(f"Hermes-API auf {API_PORT} bleibt tot — nach {attempts} Versuchen "
              f"kein weiterer Neustart.", file=sys.stderr)
        return
    note_restart_request(now, attempts + 1)
    try:
        subprocess.run(["launchctl", "kickstart", "-k",
                        f"gui/{os.getuid()}/{GATEWAY_LABEL}"],
                       capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        pass


def cmd_poll(_args: argparse.Namespace) -> int:
    now = time.time()
    state = load()
    changed = scan_gateway_log(state, now)
    if activate_pending(state, now):
        changed = True
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
    ensure_api_up()
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
        phase = "" if standin.get("live", True) else "wird eingerichtet, Empfang noch nicht bereit, "
        print(f"{standin.get('name') or key} ({key}) — {phase}noch {left:.0f} Min, {told}, "
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
        # `status` only reads; everything else is a load-modify-save that must
        # not interleave with another one.
        if args.func is cmd_status:
            return args.func(args)
        with state_lock(blocking=args.func is not cmd_poll) as acquired:
            if not acquired:
                return 0        # another command owns the state right now
            return args.func(args)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
