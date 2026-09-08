#!/usr/bin/env python3
"""Tell the user, quietly, when someone answers a WhatsApp message JARVIS sent.

JARVIS registers a watch right after sending:

    jarvis-whatsapp-watch.py watch 4915112345678@s.whatsapp.net --name "Rici"

A launchd job then runs `poll` every half minute. When that chat sends
anything back, the watch fires once — a macOS notification, plus a spoken line
if a HUD happens to be open — and clears itself.

Why the bridge log and not the bridge's own /messages endpoint: the Hermes
gateway long-polls `GET /messages`, and that call *drains* the queue. A second
reader would steal messages out from under the gateway. `bridge.log` is a
byproduct nobody consumes, so reading it disturbs nothing.

What this deliberately does NOT do: read, store or forward what anyone wrote.
It reports that a reply arrived and from whom. The bridge's accepted-message
debug records contain only redacted ids and body length, not the body itself,
and its message queue belongs to Hermes. The content stays in WhatsApp.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HOME = Path.home()
BRIDGE_LOG = Path(os.environ.get("JARVIS_WA_LOG", HOME / ".hermes/whatsapp/bridge.log"))
SESSION_DIR = Path(os.environ.get("JARVIS_WA_SESSION", HOME / ".hermes/whatsapp/session"))
STATE_PATH = Path(os.environ.get("JARVIS_WA_STATE", HOME / ".hermes/jarvis-whatsapp-watch.json"))
SAY_URL = os.environ.get("JARVIS_SAY_URL", "http://127.0.0.1:8765/api/say")
NOTIFY_URL = os.environ.get("JARVIS_NOTIFY_URL", "http://127.0.0.1:8770/notify")

# A watch is a standing promise to interrupt the user. It expires so a contact
# who answers three days later does not produce a notification out of nowhere.
DEFAULT_TTL_HOURS = 48
MORRIS_CONTACT = "4915129583256"
MORRIS_NAME = "Morris"
# Only lines the bridge writes for an inbound message it did not process.
INBOUND_REASONS = {"self_chat_mode_rejects_non_self", "allowlist_mismatch",
                   "allowlist_mismatch_owner_chat"}


# ------------------------------------------------------------------ identity

def bare(jid: str) -> str:
    """4915112345678@s.whatsapp.net -> 4915112345678, and the same for @lid."""
    return str(jid or "").strip().split("@", 1)[0].split(":", 1)[0].lstrip("+")


def aliases(jid: str) -> set[str]:
    """Every id this contact can appear under.

    WhatsApp reports inbound chats as a LID (`1332…@lid`) while a number sent
    to is a phone JID. Without walking the session's mapping files the reply
    never matches the watch — which is exactly the bug that makes a watcher
    look broken while it is working perfectly.
    """
    found: set[str] = set()
    queue = [bare(jid)]
    while queue:
        current = queue.pop()
        if not current or current in found:
            continue
        found.add(current)
        for suffix in ("", "_reverse"):
            path = SESSION_DIR / f"lid-mapping-{current}{suffix}.json"
            try:
                mapped = bare(json.loads(path.read_text()))
            except (OSError, ValueError):
                continue
            if mapped and mapped not in found:
                queue.append(mapped)
    return found


# --------------------------------------------------------------------- state

def load_state() -> dict:
    try:
        state = json.loads(STATE_PATH.read_text())
    except (OSError, ValueError):
        state = {}
    state.setdefault("watches", {})
    state.setdefault("offset", 0)
    state.setdefault("inode", 0)
    return state


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2))
    os.chmod(tmp, 0o600)   # contact numbers are personal data
    tmp.replace(STATE_PATH)


# -------------------------------------------------------------- notification

def env_token(*names: str) -> str:
    """Tokens live in ~/.hermes/.env, never in the launchd plist.

    A plist is world-readable; the env file is 600. Read it here rather than
    handing launchd a secret it would publish to every process listing.
    """
    for name in names:
        value = os.environ.get(name, "")
        if value:
            return value
    try:
        found: dict[str, str] = {}
        for line in (HOME / ".hermes/.env").read_text().splitlines():
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


def hud_token() -> str:
    return env_token("JARVIS_HUD_TOKEN", "JARVIS_APP_TOKEN")


def app_token() -> str:
    return env_token("JARVIS_APP_TOKEN", "JARVIS_HUD_TOKEN")


def notify(name: str, speak: bool) -> None:
    """Deliver the nudge through JARVIS itself, and only fall back outward.

    The app is where JARVIS lives, so that is where a nudge belongs. A macOS
    banner is the system talking, not JARVIS, and it is easy to miss on a Mac
    that is not in front of you. The system banner is therefore a backstop for
    the one case that matters — the bridge being down — not the normal path.
    """
    delivered = post_json(NOTIFY_URL, {"kind": "whatsapp_reply", "title": name,
                                       "text": "hat geantwortet"},
                          {"Authorization": f"Bearer {app_token()}"})
    if not delivered:
        system_banner(f"{name} hat geantwortet.")
    if speak:
        # Only if a HUD is open; otherwise nothing is spoken and that is fine.
        post_json(SAY_URL, {"text": f"{name} hat geantwortet.", "priority": "normal"},
                  {"X-Jarvis-Token": hud_token()})


def stop_morris_receiving() -> None:
    """Close only the receive session explicitly owned by the Morris rule.

    `off --until-reply` is a no-op unless mode.py recorded that it switched on
    receiving for Morris.  That preserves a pre-existing or later manual bot
    session.
    """
    try:
        subprocess.run([sys.executable, str(Path(__file__).with_name("jarvis-whatsapp-mode.py")),
                        "off", "--until-reply"],
                       check=False, capture_output=True, timeout=130)
    except (OSError, subprocess.SubprocessError):
        pass  # The 48-hour mode timer remains the safe backstop.


def post_json(url: str, payload: dict, headers: dict) -> bool:
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json", **headers})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        opener.open(request, timeout=8).read()
        return True
    except Exception:
        return False


def system_banner(message: str) -> None:
    try:
        # -e arguments are literal text, never a shell string, so a contact
        # named `" & do shell script "…` cannot become AppleScript.
        subprocess.run(
            ["osascript", "-e",
             'on run {msg, ttl}\n display notification msg with title ttl\nend run',
             message, "JARVIS"],
            check=False, capture_output=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        pass


# -------------------------------------------------------------------- actions

def cmd_watch(args: argparse.Namespace) -> int:
    key = bare(args.chat_id)
    if not key.isdigit() or not 8 <= len(key) <= 20:
        print(f"Keine brauchbare Chat-ID: {args.chat_id}", file=sys.stderr)
        return 2
    state = load_state()
    # A fresh send restarts the clock rather than adding a second watch.
    state["watches"][key] = {
        "name": MORRIS_NAME if key == MORRIS_CONTACT else (args.name or "").strip()[:60] or f"+{key}",
        "since": time.time(),
        "ttl_hours": args.ttl,
        "aliases": sorted(aliases(key)),
        # The bridge logs accepted bot messages as redacted debug/queued events.
        # Only the fixed Morris rule may use that weaker identity signal.
        "morris_receive_rule": key == MORRIS_CONTACT,
    }
    # Start at the end of the log: a backlog of old messages must not fire a
    # burst of notifications the moment a watch is registered.
    state["offset"], state["inode"] = log_stat()
    save_state(state)
    print(f"Beobachte {state['watches'][key]['name']} ({args.ttl} h)")
    return 0


def cmd_list(_args: argparse.Namespace) -> int:
    watches = load_state()["watches"]
    if not watches:
        print("Keine offenen Beobachtungen.")
        return 0
    now = time.time()
    for key, entry in sorted(watches.items(), key=lambda kv: kv[1].get("since", 0)):
        age = (now - entry.get("since", now)) / 3600
        print(f"{entry.get('name', key)} | +{key} | seit {age:.1f} h | "
              f"läuft ab nach {entry.get('ttl_hours', DEFAULT_TTL_HOURS)} h")
    return 0


def cmd_clear(args: argparse.Namespace) -> int:
    state = load_state()
    if args.all:
        count = len(state["watches"])
        state["watches"] = {}
    else:
        count = 1 if state["watches"].pop(bare(args.chat_id or ""), None) else 0
    save_state(state)
    print(f"{count} Beobachtung(en) entfernt.")
    return 0


def log_size() -> int:
    return log_stat()[0]


def log_stat() -> tuple[int, int]:
    """(size, inode). The inode catches a rotated log, the size a truncated one.

    A log replaced by one of byte-identical length is the single case neither
    catches; the cost is one missed nudge after a restart, and paying for it
    would mean re-scanning and risking a duplicate instead.
    """
    try:
        info = BRIDGE_LOG.stat()
        return info.st_size, info.st_ino
    except OSError:
        return 0, 0


def event_matches_watch(event: dict, key: str, entry: dict) -> bool:
    """Whether one bridge-log event is the watched contact's reply.

    Rejected messages retain their full ids.  The installed Hermes bridge logs
    allowed messages as `{event:"debug", stage:"queued"}` with ids redacted to
    their final four digits.  That is enough for the one fixed Morris rule, but
    intentionally not for ordinary watches where a suffix collision would be
    too weak an identity check.
    """
    if event.get("event") == "ignored" and event.get("reason") in INBOUND_REASONS:
        values = {bare(event.get(field, "")) for field in ("senderId", "chatId")}
        return bool(values & (set(entry.get("aliases") or [key]) | {key}))
    if not entry.get("morris_receive_rule"):
        return False
    if event.get("event") != "debug" or event.get("stage") != "queued" or event.get("fromOwner"):
        return False
    suffix = key[-4:]
    values = [bare(event.get(field, "")) for field in ("senderId", "chatId")]
    values = [value for value in values if value]
    return bool(values) and all(value.startswith("…") and value.endswith(suffix) for value in values)


def cmd_poll(args: argparse.Namespace) -> int:
    state = load_state()
    watches = state["watches"]
    now = time.time()

    expired = [key for key, entry in watches.items()
               if now - entry.get("since", now) > entry.get("ttl_hours", DEFAULT_TTL_HOURS) * 3600]
    for key in expired:
        watches.pop(key, None)

    size, inode = log_stat()
    offset = state.get("offset", 0)
    if size < offset or inode != state.get("inode", inode):
        offset = 0          # the bridge restarted, truncating or rotating its log
    state["inode"] = inode
    replies: set[str] = set()
    if watches and size > offset:
        try:
            with BRIDGE_LOG.open("rb") as handle:
                handle.seek(offset)
                blob = handle.read(4_000_000)   # a runaway log must not eat RAM
                offset += len(blob)
        except OSError:
            blob = b""
        for line in blob.decode("utf-8", "replace").splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                event = json.loads(line)
            except ValueError:
                continue
            for key, entry in watches.items():
                if event_matches_watch(event, key, entry):
                    replies.add(key)
    # With no watch open there is nothing to find, so skip to the end rather
    # than keeping a stale offset that would replay a day of log on the next one.
    state["offset"] = size if not watches else offset

    fired = []
    for key, entry in list(watches.items()):
        if key in replies:
            fired.append((entry.get("name", key), entry.get("morris_receive_rule", False)))
            watches.pop(key, None)
    save_state(state)

    for name, stop_receiving in fired:
        if stop_receiving:
            stop_morris_receiving()
        notify(name, speak=not args.quiet)
        print(f"Antwort von {name}")
    if args.verbose and not fired:
        print(f"nichts neues (offene Beobachtungen: {len(watches)})")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    watch = sub.add_parser("watch", help="einen Chat auf Antwort beobachten")
    watch.add_argument("chat_id")
    watch.add_argument("--name", default="")
    watch.add_argument("--ttl", type=float, default=DEFAULT_TTL_HOURS)
    watch.set_defaults(func=cmd_watch)

    sub.add_parser("list", help="offene Beobachtungen").set_defaults(func=cmd_list)

    clear = sub.add_parser("clear", help="Beobachtung entfernen")
    clear.add_argument("chat_id", nargs="?")
    clear.add_argument("--all", action="store_true")
    clear.set_defaults(func=cmd_clear)

    poll = sub.add_parser("poll", help="neue Antworten prüfen (launchd)")
    poll.add_argument("--quiet", action="store_true", help="nicht sprechen, nur Mitteilung")
    poll.add_argument("--verbose", action="store_true")
    poll.set_defaults(func=cmd_poll)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
