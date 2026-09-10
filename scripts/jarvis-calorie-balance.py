#!/usr/bin/env python3
"""Send the evening calorie balance to the WhatsApp group "Nährwerte Jarvis".

launchd starts this at 22:00. No model is involved: the numbers come from the
local calorie API, the text from the same report.py the Hermes tool
calories_daily_report uses, and the send goes through `hermes send`. What
arrives is exactly what the tool would return; a rate-limited free model can
neither delay, reword nor invent any of it.

At most once per day, and only between 22:00 and midnight: if the Mac slept
through 22:00, launchd runs the job on wake, and a wake the next morning must
not send yesterday's evening as today's. A failed send is reported in the
JARVIS app through jarvis-notify, never dropped silently.
"""
import datetime
import importlib.util
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

HOME = Path.home()
HERMES_DIR = HOME / ".hermes"
STATE = HERMES_DIR / "jarvis-calorie-balance.json"
# The deployed plugin copy: a launchd agent has no TCC access to ~/Documents.
REPORT = HERMES_DIR / "plugins/jarvis_calories/report.py"
HERMES = HOME / ".local/bin/hermes"
NOTIFY = HERMES_DIR / "bin/jarvis-notify"
API = os.environ.get("JARVIS_CALORIES_URL", "http://127.0.0.1:8765/api/calories")
SEND_FROM = datetime.time(22, 0)


def log(message: str) -> None:
    print(f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S} {message}", flush=True)


def env_value(name: str) -> str:
    """Tokens and the target chat live in ~/.hermes/.env (600), not in the plist."""
    if os.environ.get(name):
        return os.environ[name]
    try:
        for line in (HERMES_DIR / ".env").read_text().splitlines():
            key, _, value = line.partition("=")
            if key.strip() == name:
                return value.strip().strip("'\"")
    except OSError:
        pass
    return ""


def due(now: datetime.datetime, last_sent: str) -> bool:
    """In the evening window, and not yet today."""
    return now.time() >= SEND_FROM and last_sent != now.date().isoformat()


def last_sent() -> str:
    try:
        return json.loads(STATE.read_text()).get("sent", "")
    except (OSError, ValueError):
        return ""


def mark_sent(day: str) -> None:
    STATE.write_text(json.dumps({"sent": day}) + "\n")


def summary_for(day: str) -> dict:
    token = env_value("JARVIS_HUD_TOKEN")
    request = urllib.request.Request(
        f"{API.rstrip('/')}/days/{day}",
        headers={"X-Jarvis-Token": token, "Authorization": f"Bearer {token}"})
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=15) as response:
        summary = json.loads(response.read())
    if not isinstance(summary, dict) or summary.get("ok") is False:
        raise ValueError(f"unexpected answer: {str(summary)[:120]}")
    return summary


def format_balance(summary: dict) -> str:
    spec = importlib.util.spec_from_file_location("jarvis_calorie_report", REPORT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.format_daily_balance(summary)


def notify(title: str, text: str) -> None:
    subprocess.run([sys.executable, str(NOTIFY), title, "--text", text, "--kind", "info"],
                   check=False, timeout=30)


def main() -> int:
    now = datetime.datetime.now()
    if not due(now, last_sent()):
        log("nichts zu tun")
        return 0
    chat = env_value("JARVIS_CALORIE_REPORT_CHAT")
    if not chat.endswith(("@g.us", "@s.whatsapp.net")):
        notify("Kalorienbilanz nicht gesendet", "Kein gültiger Zielchat in JARVIS_CALORIE_REPORT_CHAT.")
        log("kein gültiger Zielchat")
        return 1
    day = now.date().isoformat()
    try:
        message = format_balance(summary_for(day))
    except Exception as exc:
        notify("Kalorienbilanz nicht gesendet", f"Die Kalorien-API antwortet nicht ({type(exc).__name__}).")
        log(f"API oder Format: {exc}")
        return 1
    sent = subprocess.run(
        [str(HERMES), "send", "--to", f"whatsapp:{chat}", "--quiet", "--file", "-"],
        input=message, text=True, capture_output=True, timeout=120)
    if sent.returncode != 0:
        reason = (sent.stderr or sent.stdout).strip()[-180:] or f"hermes send: Exit {sent.returncode}"
        notify("Kalorienbilanz nicht gesendet", reason)
        log(f"Versand fehlgeschlagen: {reason}")
        return 1
    mark_sent(day)
    log(f"Bilanz für {day} an Nährwerte Jarvis gesendet")
    return 0


if __name__ == "__main__":
    sys.exit(main())
