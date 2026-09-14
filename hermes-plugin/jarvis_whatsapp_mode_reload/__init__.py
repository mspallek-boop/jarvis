"""Take a new WhatsApp receive mode into the running gateway, without a restart.

`scripts/jarvis-whatsapp-mode.py` switches WhatsApp receiving by rewriting four
keys in ~/.hermes/.env. The gateway reads .env once, at start, and the bridge
takes its mode from that copy whenever it is spawned. So every switch used to
restart the whole gateway: API turns running in the app were cut off
("Operation interrupted") and the app lost Hermes for one to three minutes.

Only the bridge needs the new mode, and Hermes already respawns a bridge that
dies (it reconnected in five seconds when tested on 2026-09-14). What was
missing is the new value inside the gateway process. This plugin is that half:
on request it copies the managed keys from .env into os.environ and confirms.
The mode script then stops only the bridge, checks that the replacement runs
with the expected `--mode`, and falls back to the full restart otherwise.

The request is a file, not a tool or an HTTP route: the switch runs from
launchd and from Hermes turns alike, and neither should need a model or a
token to reach the gateway. Only the four managed keys are touched, never the
rest of .env, which holds every credential on the machine.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# Kept in lockstep with MANAGED in scripts/jarvis-whatsapp-mode.py.
MANAGED = ("WHATSAPP_MODE", "WHATSAPP_ALLOWED_USERS",
           "WHATSAPP_FORWARD_OWNER_MESSAGES", "WHATSAPP_DEBUG")
POLL_SECONDS = 1.0

_started = False
_start_lock = threading.Lock()


def _reload_dir() -> Path:
    return Path(os.environ.get("JARVIS_WA_RELOAD_DIR", Path.home() / ".hermes"))


def request_path() -> Path:
    return _reload_dir() / "jarvis-whatsapp-reload.request"


def ack_path() -> Path:
    return _reload_dir() / "jarvis-whatsapp-reload.ack"


def alive_path() -> Path:
    return _reload_dir() / "jarvis-whatsapp-reload.alive"


def env_path() -> Path:
    return Path(os.environ.get("JARVIS_WA_ENV", Path.home() / ".hermes/.env"))


def read_managed(path: Path) -> dict[str, str]:
    """The managed keys as the mode script writes them; nothing else is read into memory."""
    values: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        if name.strip() in MANAGED:
            values[name.strip()] = value.strip().strip("'\"")
    return values


def apply(values: dict[str, str], environ=None) -> None:
    """Set the managed keys from `values`; a key the file no longer has is removed.

    Removal matters: `off` deletes WHATSAPP_FORWARD_OWNER_MESSAGES and
    WHATSAPP_DEBUG from .env, and a value left behind in the process would ride
    into the next bridge.
    """
    environ = os.environ if environ is None else environ
    for key in MANAGED:
        if key in values:
            environ[key] = values[key]
        else:
            environ.pop(key, None)


def _write_private(path: Path, payload: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload))
    os.chmod(tmp, 0o600)
    tmp.replace(path)


def handle_request(raw: str) -> dict | None:
    """Apply .env for one request and write the acknowledgement. None for a bad request."""
    try:
        request_id = str(json.loads(raw)["id"])
    except (ValueError, KeyError, TypeError):
        return None
    try:
        apply(read_managed(env_path()))
    except OSError as exc:
        logger.warning("jarvis_whatsapp_mode_reload: could not read .env: %s", exc)
        return None
    # The mode only, not the allowlist: the acknowledgement need not carry numbers.
    ack = {"id": request_id, "pid": os.getpid(),
           "mode": os.environ.get("WHATSAPP_MODE", "self-chat"), "at": time.time()}
    _write_private(ack_path(), ack)
    logger.info("jarvis_whatsapp_mode_reload: WhatsApp keys reloaded (mode %s)", ack["mode"])
    return ack


def _read_request() -> str | None:
    try:
        return request_path().read_text()
    except OSError:
        return None


def _watch() -> None:
    _write_private(alive_path(), {"pid": os.getpid(), "started": time.time()})
    # A request left over from an earlier gateway was answered by that gateway.
    last = _read_request()
    while True:
        raw = _read_request()
        if raw and raw != last:
            last = raw
            try:
                handle_request(raw)
            except Exception:  # never let one bad request end the watcher
                logger.exception("jarvis_whatsapp_mode_reload: request failed")
        time.sleep(POLL_SECONDS)


def in_gateway(argv=None) -> bool:
    """Plugins load in every Hermes process; only the gateway spawns the bridge."""
    argv = sys.argv if argv is None else argv
    return "gateway" in argv and "run" in argv


def register(ctx):
    global _started
    if not in_gateway():
        return
    with _start_lock:
        if _started:
            return
        _started = True
    threading.Thread(target=_watch, name="jarvis-whatsapp-mode-reload", daemon=True).start()
