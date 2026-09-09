#!/usr/bin/env python3
"""Turn WhatsApp receiving on and off, optionally for a set time.

    jarvis-whatsapp-mode.py status
    jarvis-whatsapp-mode.py on --contact 4915112345678 --for 2h
    jarvis-whatsapp-mode.py on --contact 4915129583256 --for 48h --until-reply
    jarvis-whatsapp-mode.py off

Default is off, and off is the safe state. While it is on, Hermes **answers
incoming WhatsApp messages from the listed contacts by itself** — that is what
bot mode is, and it is why this is a deliberate switch with a timer rather than
a setting someone flips and forgets. Nothing here ever adds `*`: an open bot
would answer strangers.

Three keys move together, because bot mode alone breaks two working things:

  WHATSAPP_MODE=bot                   the actual switch
  WHATSAPP_FORWARD_OWNER_MESSAGES=1   without it, bot mode drops the user's own
                                      messages and the WhatsApp chat with
                                      JARVIS goes dead
  WHATSAPP_DEBUG=1                    without it, accepted messages stop being
                                      logged and jarvis-whatsapp-watch.py goes
                                      blind for exactly those contacts

`off` restores every key to the value it had before, from the state file, so a
setting the user changed by hand is not silently overwritten with a guess.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

HOME = Path.home()
ENV_PATH = Path(os.environ.get("JARVIS_WA_ENV", HOME / ".hermes/.env"))
STATE_PATH = Path(os.environ.get("JARVIS_WA_MODE_STATE", HOME / ".hermes/jarvis-whatsapp-mode.json"))
MANAGED = ("WHATSAPP_MODE", "WHATSAPP_ALLOWED_USERS",
           "WHATSAPP_FORWARD_OWNER_MESSAGES", "WHATSAPP_DEBUG")
MAX_HOURS = 24 * 7
# This is deliberately a fixed, one-contact exception.  A reply watcher calls
# `off --until-reply`, which only acts when this invocation owns bot mode.
MORRIS_CONTACT = "4915129583256"
UNTIL_REPLY_STATE_KEYS = ("until_reply_contact", "until_reply_existing_mode",
                          "until_reply_added_contact", "until_reply_until")


# ----------------------------------------------------------------- .env access

def read_env() -> dict[str, str]:
    """Only the keys this tool manages. The rest of the file is secrets."""
    values: dict[str, str] = {}
    try:
        for line in ENV_PATH.read_text().splitlines():
            line = line.strip()
            if line.startswith("#") or "=" not in line:
                continue
            name, _, value = line.partition("=")
            if name.strip() in MANAGED:
                values[name.strip()] = value.strip().strip("'\"")
    except OSError:
        pass
    return values


def write_env(changes: dict[str, str | None]) -> None:
    """Set or remove keys, leaving every other byte of the file untouched.

    The file holds every credential on this machine, so it is rewritten whole
    only via a 600 temp file and an atomic replace — a half-written .env would
    take down Hermes, the bridge and the voice server at once.
    """
    original = ENV_PATH.read_text()
    lines = original.splitlines()
    seen: set[str] = set()
    result: list[str] = []
    for line in lines:
        stripped = line.strip()
        name = stripped.partition("=")[0].strip()
        if stripped.startswith("#") or "=" not in stripped or name not in changes:
            result.append(line)
            continue
        value = changes[name]
        seen.add(name)
        if value is not None:
            result.append(f"{name}={value}")
        # value None: drop the line entirely
    for name, value in changes.items():
        if name not in seen and value is not None:
            result.append(f"{name}={value}")

    backup = ENV_PATH.with_suffix(f".env.bak.wamode.{time.strftime('%Y%m%d_%H%M%S')}")
    backup.write_text(original)
    os.chmod(backup, 0o600)
    tmp = ENV_PATH.with_suffix(".env.tmp")
    tmp.write_text("\n".join(result) + "\n")
    os.chmod(tmp, 0o600)
    tmp.replace(ENV_PATH)


def load_state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text())
    except (OSError, ValueError):
        return {}


def save_state(state: dict) -> None:
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2))
    os.chmod(tmp, 0o600)
    tmp.replace(STATE_PATH)


def hermes_binary() -> str:
    """Find `hermes` even when nobody set up a PATH.

    launchd hands a job the bare system PATH, and `hermes` lives in
    ~/.local/bin. A scheduled expiry therefore wrote the env correctly and then
    failed to restart the gateway — reporting failure for a change that had
    actually been made, which is the worst of both.
    """
    return (shutil.which("hermes")
            or (str(Path.home() / ".local/bin/hermes")
                if (Path.home() / ".local/bin/hermes").exists() else "hermes"))


def restart_gateway() -> bool:
    try:
        done = subprocess.run([hermes_binary(), "gateway", "restart"],
                              capture_output=True, timeout=120)
        return done.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


# --------------------------------------------------------------------- helpers

def parse_duration(text: str) -> float:
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*([hmd])\s*", text.lower())
    if not match:
        raise argparse.ArgumentTypeError("Dauer wie 90m, 2h oder 1d angeben")
    hours = float(match.group(1)) * {"m": 1 / 60, "h": 1, "d": 24}[match.group(2)]
    if not 0 < hours <= MAX_HOURS:
        raise argparse.ArgumentTypeError(f"Dauer muss zwischen 0 und {MAX_HOURS} h liegen")
    return hours


def clean_contact(value: str) -> str:
    """Accept anything the user might dictate or paste: "+49 170 123 45 67",
    "0049…", a bare number, or a full chat id."""
    digits = value.strip().split("@", 1)[0].split(":", 1)[0]
    digits = re.sub(r"[\s/().·-]", "", digits).lstrip("+")
    if digits.startswith("00"):
        digits = digits[2:]
    if not digits.isdigit() or not 8 <= len(digits) <= 20:
        raise argparse.ArgumentTypeError(f"Keine brauchbare Nummer: {value}")
    return digits


def describe(env: dict, state: dict) -> str:
    mode = env.get("WHATSAPP_MODE", "self-chat")
    allowed = [v for v in env.get("WHATSAPP_ALLOWED_USERS", "").split(",") if v.strip()]
    lines = [f"Modus:      {mode}"]
    if mode == "bot":
        until = state.get("until")
        if until:
            left = (until - time.time()) / 60
            lines.append(f"Läuft ab:   in {left:.0f} min ({time.strftime('%H:%M', time.localtime(until))})")
        else:
            lines.append("Läuft ab:   nie — bleibt an, bis du 'off' sagst")
        lines.append(f"Empfängt von: {', '.join('+' + a for a in allowed) or '(niemandem)'}")
        lines.append("JARVIS antwortet diesen Kontakten selbständig.")
    else:
        lines.append("Empfangen:  aus. JARVIS liest keine fremden Nachrichten und")
        lines.append("            antwortet niemandem von selbst. Senden geht normal,")
        lines.append("            und der Antwort-Watcher meldet weiterhin Antworten.")
    return "\n".join(lines)


# --------------------------------------------------------------------- commands

def cmd_status(_args) -> int:
    print(describe(read_env(), load_state()))
    return 0


def cmd_on(args) -> int:
    env = read_env()
    contacts = sorted({c for c in args.contact})
    if not contacts:
        print("Mindestens einen Kontakt angeben (--contact 4915112345678).\n"
              "Ohne Kontakte empfängt der Bot-Modus nichts — die Allowlist verwirft alles.",
              file=sys.stderr)
        return 2
    if args.until_reply and contacts != [MORRIS_CONTACT]:
        print("--until-reply ist nur für den fest hinterlegten Morris-Chat erlaubt.",
              file=sys.stderr)
        return 2
    if args.until_reply and env.get("WHATSAPP_MODE") == "bot":
        # Existing receiving is user-owned. Add Morris only when needed, and
        # later remove only that addition rather than switching bot mode off.
        existing = [v for v in env.get("WHATSAPP_ALLOWED_USERS", "").split(",") if v.strip()]
        if MORRIS_CONTACT in existing:
            print("WhatsApp-Empfang für Morris läuft bereits und bleibt user-verwaltet.")
            return 0
        state = load_state()
        state.update({"until_reply_contact": MORRIS_CONTACT,
                      "until_reply_existing_mode": True,
                      "until_reply_added_contact": True,
                      "until_reply_until": time.time() + args.duration * 3600})
        save_state(state)
        write_env({"WHATSAPP_ALLOWED_USERS": ",".join(sorted(set(existing) | {MORRIS_CONTACT}))})
        ok = restart_gateway()
        print(describe(read_env(), load_state()))
        print("Gateway neu gestartet." if ok else
              "ACHTUNG: Gateway-Neustart fehlgeschlagen — 'hermes gateway restart' von Hand.")
        return 0 if ok else 1
    if env.get("WHATSAPP_MODE") != "bot":
        # Only the first activation records the truth; a second `on` must not
        # overwrite the saved state with the already-modified values.
        save_state({"previous": {key: env.get(key) for key in MANAGED},
                    "until": None})
    state = load_state()

    existing = [v for v in env.get("WHATSAPP_ALLOWED_USERS", "").split(",") if v.strip()]
    # The union is right for a person switching receiving on by hand: it must
    # not silently drop someone another session is relying on. It is wrong for
    # a caller that owns the whole list — a contact whose reason to be there
    # has ended would otherwise stay, and keep being answered by nobody's
    # decision. `--exclusive` is for that caller.
    allowed = sorted(set(contacts) if args.exclusive else set(existing) | set(contacts))
    state["until"] = time.time() + args.duration * 3600 if args.duration else None
    if args.until_reply:
        state["until_reply_contact"] = MORRIS_CONTACT
        state["until_reply_until"] = state["until"]
    else:
        # A manual follow-up activation takes ownership back from the automatic
        # Morris window, so its watcher cannot unexpectedly turn it off.
        for key in UNTIL_REPLY_STATE_KEYS:
            state.pop(key, None)
    save_state(state)
    write_env({
        "WHATSAPP_MODE": "bot",
        "WHATSAPP_ALLOWED_USERS": ",".join(allowed),
        "WHATSAPP_FORWARD_OWNER_MESSAGES": "true",
        "WHATSAPP_DEBUG": "true",
    })
    ok = restart_gateway()
    print(describe(read_env(), load_state()))
    print("Gateway neu gestartet." if ok else
          "ACHTUNG: Gateway-Neustart fehlgeschlagen — 'hermes gateway restart' von Hand.")
    return 0 if ok else 1


def cmd_off(_args) -> int:
    state = load_state()
    if getattr(_args, "until_reply", False) and state.get("until_reply_contact") != MORRIS_CONTACT:
        # This is intentionally a no-op unless the fixed Morris activation
        # created the current receive window.
        return 0
    if getattr(_args, "until_reply", False) and state.get("until_reply_existing_mode"):
        # Morris was added to an already-running user session.  Restore only
        # that allowlist entry and preserve its mode, timer and other contacts.
        if state.get("until_reply_added_contact"):
            env = read_env()
            allowed = [value for value in env.get("WHATSAPP_ALLOWED_USERS", "").split(",")
                       if value.strip() and value != MORRIS_CONTACT]
            write_env({"WHATSAPP_ALLOWED_USERS": ",".join(allowed)})
            ok = restart_gateway()
        else:
            ok = True
        for key in UNTIL_REPLY_STATE_KEYS:
            state.pop(key, None)
        save_state(state)
        return 0 if ok else 1
    previous = state.get("previous") or {}
    if not previous and read_env().get("WHATSAPP_MODE") != "bot":
        print(describe(read_env(), state))
        return 0
    # Fall back to the safe default rather than leaving bot mode on because a
    # state file went missing.
    write_env({key: previous.get(key) for key in MANAGED}
              if previous else {"WHATSAPP_MODE": "self-chat",
                                "WHATSAPP_FORWARD_OWNER_MESSAGES": None,
                                "WHATSAPP_DEBUG": None})
    save_state({})
    ok = restart_gateway()
    print(describe(read_env(), {}))
    print("Gateway neu gestartet." if ok else
          "ACHTUNG: Gateway-Neustart fehlgeschlagen — 'hermes gateway restart' von Hand.")
    return 0 if ok else 1


def cmd_enforce(args) -> int:
    """Called by launchd: switch back when the time is up."""
    state = load_state()
    until = state.get("until")
    if until and time.time() >= until:
        print(f"Zeit abgelaufen — WhatsApp-Empfang wird abgeschaltet "
              f"({time.strftime('%Y-%m-%d %H:%M:%S')})")
        return cmd_off(args)
    reply_until = state.get("until_reply_until")
    if reply_until and time.time() >= reply_until:
        print(f"Zeit abgelaufen — Morris-Empfang wird abgeschaltet "
              f"({time.strftime('%Y-%m-%d %H:%M:%S')})")
        return cmd_off(argparse.Namespace(until_reply=True))
    if not until or time.time() < until:
        if args.verbose:
            print("nichts zu tun")
        return 0
    print(f"Zeit abgelaufen — WhatsApp-Empfang wird abgeschaltet "
          f"({time.strftime('%Y-%m-%d %H:%M:%S')})")
    return cmd_off(args)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="aktueller Zustand").set_defaults(func=cmd_status)

    on = sub.add_parser("on", help="Empfangen einschalten (JARVIS antwortet dann selbst)")
    on.add_argument("--contact", action="append", type=clean_contact, default=[],
                    help="Nummer, von der empfangen werden darf (mehrfach möglich)")
    on.add_argument("--for", dest="duration", type=parse_duration, default=None,
                    metavar="DAUER", help="z. B. 90m, 2h, 1d — danach automatisch aus")
    on.add_argument("--exclusive", action="store_true",
                    help="die Liste auf genau diese Nummern setzen statt zu ergänzen")
    on.add_argument("--until-reply", action="store_true",
                    help=argparse.SUPPRESS)
    on.set_defaults(func=cmd_on)

    off = sub.add_parser("off", help="Empfangen abschalten")
    off.add_argument("--until-reply", action="store_true", help=argparse.SUPPRESS)
    off.set_defaults(func=cmd_off)

    enforce = sub.add_parser("enforce", help="abgelaufene Zeitbegrenzung durchsetzen (launchd)")
    enforce.add_argument("--verbose", action="store_true")
    enforce.set_defaults(func=cmd_enforce)

    args = parser.parse_args()
    if not hasattr(args, "verbose"):
        args.verbose = False
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
