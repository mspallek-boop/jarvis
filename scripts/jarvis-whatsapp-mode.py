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
import contextlib
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


GATEWAY_LABEL = "ai.hermes.gateway"
GATEWAY_PLIST = Path.home() / "Library/LaunchAgents" / f"{GATEWAY_LABEL}.plist"
# The port the JARVIS app reaches Hermes on, and how long a replacement
# gateway may take to claim it before we assume it never will.
API_PORT = int(os.environ.get("JARVIS_HERMES_API_PORT", "8642"))
API_WAIT_SECONDS = 45.0
# How long the sequenced restart waits for the old gateway to release the API
# port after a clean stop, before it starts the replacement. A clean SIGTERM
# exit frees it in well under a second; the ceiling only guards a slow shutdown.
PORT_FREE_WAIT_SECONDS = 20.0
# How long the sequenced restart lets API turns that are still streaming finish
# before it stops the gateway — usually the very turn that ordered the switch.
DRAIN_WAIT_SECONDS = 120.0
# A server-side TIME_WAIT lives 2*MSL: 30s with macOS's default MSL of 15s.
TIME_WAIT_SECONDS = 40.0
# Shared with jarvis-chat-standin.py: both may decide a restart is due within
# the same minute, and two `kickstart -k` on top of each other kill the
# gateway the first one just started. The poller owns the cooldown; this side
# only writes the stamp while it is trying, and clears it when it gives up.
RESTART_STAMP = Path(os.environ.get("JARVIS_RESTART_STAMP",
                                    Path.home() / ".hermes/jarvis-gateway-restart.stamp"))


def api_listeners() -> set:
    """The pids holding the app's Hermes port, or None when it cannot be told.

    Asked with `lsof` rather than by connecting: a mode switch must not make a
    network call. The pids matter and not just a yes/no — during the race the
    *old* listener still holds the port for a moment, and a plain "is it
    bound?" would report the restart as a success while the replacement was
    still about to fail to bind.
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
    pids = api_listeners()
    return True if pids is None else bool(pids)


def await_new_api(before, seconds: float) -> bool:
    """Wait until the port is held by a process that was not holding it before.

    `before` is None when lsof could not answer at all; there is nothing to
    compare against then, so any listener counts and the caller is no worse
    off than before this check existed.

    Seeing the port empty at any point settles it on its own: the old listener
    is provably gone, so whoever holds it next is the replacement even if the
    kernel handed it the same pid. Without that, pid reuse reads as "nothing
    changed" and costs a second, pointless restart.
    """
    deadline = time.time() + seconds
    released = False
    while time.time() < deadline:
        now_pids = api_listeners()
        if now_pids is None:
            return True
        if not now_pids:
            released = True
        elif released or before is None or now_pids - before:
            return True
        time.sleep(1.0)
    return False


def note_restart_request() -> None:
    """Tell the poller a restart is in flight, so it does not add a second."""
    try:
        RESTART_STAMP.parent.mkdir(parents=True, exist_ok=True)
        RESTART_STAMP.write_text(f"{time.time()} 1")
    except OSError:
        pass


def clear_restart_claim() -> None:
    """Hand the problem back after giving up.

    The stamp exists to stop two restarts landing on top of each other. Once
    this script has tried twice and failed, holding it for the rest of the
    cooldown only stops the minute-by-minute poller from attempting the repair
    that is now its job.
    """
    try:
        RESTART_STAMP.unlink()
    except OSError:
        pass


def await_port_free(seconds: float) -> bool:
    """Wait until no process holds the API port, i.e. the old gateway let go.

    Mirrors `api_listeners`' None-means-unknown contract: if lsof cannot answer
    we do not block, because a restart must not stall on a diagnostic failure.
    """
    deadline = time.time() + seconds
    while time.time() < deadline:
        pids = api_listeners()
        if pids is None or not pids:
            return True
        time.sleep(0.5)
    return False


def api_sockets():
    """States of the TCP sockets whose *local* end is the API port, LISTEN aside.

    Asked with netstat, not lsof: a TIME_WAIT has no owning process, so lsof
    never shows it — and a TIME_WAIT is what actually loses the port. Hermes
    binds 8642 without SO_REUSEADDR on macOS, so any socket still sitting on
    that port makes the replacement fail with `address already in use`, which
    Hermes treats as a permanent conflict: api_server is dropped and the
    gateway runs on WhatsApp-only. None means netstat could not answer.
    """
    try:
        done = subprocess.run(["netstat", "-an", "-p", "tcp"],
                              capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return None
    output = getattr(done, "stdout", None)
    if output is None:
        return None
    states = []
    for line in output.splitlines():
        cols = line.split()
        if (len(cols) >= 6 and cols[0].startswith("tcp")
                and cols[3].endswith(f".{API_PORT}") and cols[5] != "LISTEN"):
            states.append(cols[5])
    return states


def await_api_sockets_gone(seconds: float, states=None) -> bool:
    """Wait until no socket on the API port is in one of `states` (any, if None).

    Same None-means-unknown contract as `await_port_free`: never block a
    restart on a diagnostic that cannot answer.
    """
    deadline = time.time() + seconds
    while time.time() < deadline:
        found = api_sockets()
        if found is None or not [s for s in found if states is None or s in states]:
            return True
        time.sleep(1.0)
    return False


def sequenced_reload() -> int:
    """Restart the gateway without leaving the API port blocked. Runs detached.

    Launched in its own session by `_spawn_detached_reload`, so the SIGTERM
    that stops the gateway cannot take this process down with the gateway child
    that asked for the restart.

    The port is lost to TIME_WAIT, not to the old listener. Stopping the
    gateway cuts off every API turn still streaming — normally the very turn
    that ordered the stand-in — and each cut leaves a server-side TIME_WAIT on
    8642 for 30s. launchd respawns the gateway within seconds, its bind fails,
    and the app shows "Hermes nicht erreichbar" until a second restart. Waiting
    for the listener to disappear could never see that. So open turns finish
    first; and if the replacement still comes up without its API, the TIME_WAIT
    is waited out before the one recovery kick instead of kicking into it blind.
    """
    target = f"gui/{os.getuid()}/{GATEWAY_LABEL}"
    before = api_listeners()
    note_restart_request()
    await_api_sockets_gone(DRAIN_WAIT_SECONDS, {"ESTABLISHED"})
    # Stop, don't -k: a clean exit releases the port before anyone asks for it.
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        subprocess.run(["launchctl", "kill", "TERM", target],
                       capture_output=True, timeout=30)
    await_port_free(PORT_FREE_WAIT_SECONDS)
    # KeepAlive may already be relaunching; kickstart (no -k) only ensures it
    # is running, and starts it promptly if KeepAlive is throttling the respawn.
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        subprocess.run(["launchctl", "kickstart", target],
                       capture_output=True, timeout=30)
    if await_new_api(before, API_WAIT_SECONDS):
        return 0
    # Came up without its API: let the port go quiet, then kill-and-restart.
    await_api_sockets_gone(TIME_WAIT_SECONDS)
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        subprocess.run(["launchctl", "kickstart", "-k", target],
                       capture_output=True, timeout=30)
    if await_new_api(api_listeners(), API_WAIT_SECONDS):
        return 0
    clear_restart_claim()
    return 1


def _spawn_detached_reload() -> bool:
    """Start `sequenced_reload` in its own session so the gateway restart it
    triggers cannot kill it. Returns True once the child is launched."""
    try:
        subprocess.Popen(
            [sys.executable, os.path.abspath(__file__), "_reload"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, start_new_session=True, close_fds=True)
        return True
    except (OSError, ValueError):
        return False


def restart_gateway() -> bool:
    """Reload the gateway after a mode change, without dropping the API port.

    A mode switch normally runs as a child of the gateway, so it cannot
    stop-then-start inline: the stop would kill this process first. It hands
    the restart to a detached sequencer (`sequenced_reload`, in its own
    session) that stops the gateway, waits for port 8642 to be released, and
    only then starts the replacement — so api_server binds cleanly instead of
    racing the old listener. That race is what made ordering a WhatsApp
    Vertretung drop Hermes for the app while the stand-in kept answering.

    Returning True means the restart was launched: the mode env is already
    written, WhatsApp receiving comes up, and the sequencer (backed by the
    poller's `ensure_api_up`) brings the API port back. If the detach cannot be
    launched, fall back to the atomic `kickstart -k` with reactive retry, then
    the CLI.
    """
    if GATEWAY_PLIST.exists() and _spawn_detached_reload():
        note_restart_request()
        return True
    # Fallback: the original in-process atomic restart with two-shot recovery.
    before = api_listeners()
    if GATEWAY_PLIST.exists():
        try:
            done = subprocess.run(
                ["launchctl", "kickstart", "-k", f"gui/{os.getuid()}/{GATEWAY_LABEL}"],
                capture_output=True, timeout=30)
            if done.returncode == 0:
                note_restart_request()
                if await_new_api(before, API_WAIT_SECONDS):
                    return True
                before = api_listeners()
                try:
                    subprocess.run(
                        ["launchctl", "kickstart", "-k",
                         f"gui/{os.getuid()}/{GATEWAY_LABEL}"],
                        capture_output=True, timeout=30)
                except (OSError, subprocess.SubprocessError):
                    return False
                note_restart_request()
                if await_new_api(before, API_WAIT_SECONDS):
                    return True
                clear_restart_claim()
                return False
        except (OSError, subprocess.SubprocessError):
            pass
        # Fall through: an uninstalled or renamed service is a reason to try
        # the CLI, not a reason to report a failed switch.
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


def cmd_reload(_args) -> int:
    """Hidden: the detached body of restart_gateway (see _spawn_detached_reload)."""
    return sequenced_reload()


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

    # Hidden: detached sequenced restart, spawned by restart_gateway itself.
    sub.add_parser("_reload").set_defaults(func=cmd_reload)

    args = parser.parse_args()
    if not hasattr(args, "verbose"):
        args.verbose = False
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
