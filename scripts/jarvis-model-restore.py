#!/usr/bin/env python3
"""Put JARVIS back on gpt-5.6-luna once the ChatGPT Plus (Codex) quota returns.

While Codex was out of quota (until 2026-09-15 07:11), Hermes ran on the free
Nous model poolside. A session that fell back during the outage keeps that
model pinned in its row, so switching the config back alone would leave the
app's conversations on the free model. launchd runs this hourly; it:

1. does nothing before RESTORE_AFTER, or once it has succeeded;
2. proves Codex answers: a throwaway API session locked to gpt-5.6-luna, and
   the agent log must show the call going to openai-codex — a reply alone
   proves nothing, the fallback chain would answer too;
3. swaps the model blocks of ~/.hermes/config.yaml back (backup first), but
   only if they are still exactly the ones written on 2026-09-10;
4. re-locks every recent API session pinned to a free Nous model;
5. proves a fresh session now lands on Codex, tells the app, and unloads.

Deterministic on purpose: no agent decides anything here.
"""
import datetime
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HOME = Path.home()
HERMES = HOME / ".hermes"
CONFIG = HERMES / "config.yaml"
STATE_DB = HERMES / "state.db"
AGENT_LOG = HERMES / "logs/agent.log"
DONE = HERMES / "jarvis-model-restore.done"
NOTIFY = HERMES / "bin/jarvis-notify"
API = os.environ.get("HERMES_API_URL", "http://127.0.0.1:8642")
LABEL = "com.jarvis.model-restore"

RESTORE_AFTER = datetime.datetime(2026, 9, 15, 7, 15)
GIVE_UP_AFTER = datetime.datetime(2026, 9, 22, 7, 15)
TARGET = {"model": "gpt-5.6-luna", "provider": "openai-codex"}
FREE_PREFIXES = ("poolside/", "meituan/longcat", "nvidia/nemotron")

TEMP_BLOCK = ("model:\n  base_url: https://inference-api.nousresearch.com/v1\n"
              "  default: poolside/laguna-s-2.1:free\n  provider: nous\n")
CODEX_BLOCK = "model:\n  base_url: ''\n  default: gpt-5.6-luna\n  provider: openai-codex\n"
# Nemotron was tried first and is not in Nous' catalogue (404); LongCat answers.
TEMP_FALLBACK = "fallback_model:\n  provider: nous\n  model: meituan/longcat-2.0:free\n"
# With Codex primary again, the fast free model is the better stand-in.
CODEX_FALLBACK = "fallback_model:\n  provider: nous\n  model: poolside/laguna-s-2.1:free\n"


def log(message: str) -> None:
    print(f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S} {message}", flush=True)


def due(now: datetime.datetime) -> bool:
    return now >= RESTORE_AFTER


def restored_config(text: str):
    """The config with Codex primary again, or None if it is no longer ours to change."""
    if text.count(TEMP_BLOCK) != 1:
        return None
    text = text.replace(TEMP_BLOCK, CODEX_BLOCK, 1)
    if text.count(TEMP_FALLBACK) == 1:
        text = text.replace(TEMP_FALLBACK, CODEX_FALLBACK, 1)
    return text


def api_key() -> str:
    for line in (HERMES / ".env").read_text().splitlines():
        key, _, value = line.partition("=")
        if key.strip() == "API_SERVER_KEY":
            return value.strip().strip("'\"")
    raise SystemExit("API_SERVER_KEY fehlt in ~/.hermes/.env")


def call(method: str, path: str, payload=None, timeout: int = 30) -> str:
    request = urllib.request.Request(
        API + path, method=method,
        data=None if payload is None else json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key()}", "Content-Type": "application/json"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=timeout) as response:
        return response.read().decode("utf-8", "replace")


def new_session(title: str) -> str:
    body = json.loads(call("POST", "/api/sessions", {"title": title}))
    return body.get("id") or body.get("session_id") or (body.get("session") or {}).get("id")


def lock(session_id: str) -> None:
    call("POST", f"/api/sessions/{session_id}/model", TARGET)


def answered_by_codex(session_id: str) -> bool:
    try:
        call("POST", f"/api/sessions/{session_id}/chat/stream", {"input": "Antworte nur mit: OK"}, timeout=240)
    except Exception as exc:   # a rate-limited locked session waits 600 s; that is a "not yet"
        log(f"Probe {session_id}: {exc}")
        return False
    marker = f"[{session_id}] agent.conversation_loop: API call #"
    lines = AGENT_LOG.read_text(errors="replace").splitlines()[-5000:]
    return any(marker in line and "provider=openai-codex" in line for line in lines)


def pinned_sessions() -> list:
    with sqlite3.connect(f"file:{STATE_DB}?mode=ro", uri=True) as db:
        rows = db.execute("select id, model from sessions where id like 'api_%' "
                          "and last_activity_at > strftime('%s','now','-14 days')").fetchall()
    return [session_id for session_id, model in rows if model and model.startswith(FREE_PREFIXES)]


HERMES_AGENT = HERMES / "hermes-agent"
HERMES_PY = HERMES_AGENT / "venv/bin/python"
# Hermes' own SessionDB, not the lock endpoint: a Browser lock also switches off
# the fallback chain (a rate-limited locked session waits 600 s instead of moving
# on), and update_session_model sets model + provider while dropping any lock.
REPIN = """
import json, sys
from pathlib import Path
from hermes_state import SessionDB
ids, model, provider = json.loads(sys.argv[1]), sys.argv[2], sys.argv[3]
with SessionDB(Path(sys.argv[4])) as db:   # a str has no .parent: SessionDB wants a Path
    for session_id in ids:
        db.update_session_model(session_id, model, provider)
print(len(ids))
"""


def repin(session_ids: list) -> int:
    if not session_ids:
        return 0
    done = subprocess.run(
        [str(HERMES_PY), "-c", REPIN, json.dumps(session_ids), TARGET["model"], TARGET["provider"], str(STATE_DB)],
        cwd=HERMES_AGENT, capture_output=True, text=True, timeout=60)
    if done.returncode != 0:
        log(f"Umstellen fehlgeschlagen: {done.stderr.strip()[-300:]}")
        return 0
    return int(done.stdout.strip() or 0)


def notify(title: str, text: str) -> None:
    subprocess.run([sys.executable, str(NOTIFY), title, "--text", text, "--kind", "info"],
                   check=False, timeout=30)


def finish() -> None:
    DONE.write_text(f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S}\n")
    log("fertig — Job entlädt sich")
    subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}/{LABEL}"], check=False)


def main() -> int:
    now = datetime.datetime.now()
    if DONE.exists():
        return 0
    if not due(now):
        log(f"noch nicht fällig (ab {RESTORE_AFTER:%d.%m. %H:%M})")
        return 0
    if now > GIVE_UP_AFTER:
        notify("Hauptmodell nicht zurückgestellt",
               "Codex antwortet seit einer Woche nicht. JARVIS bleibt auf poolside, bitte selbst prüfen.")
        finish()
        return 1

    probe = new_session("model-restore: Codex-Probe")
    lock(probe)
    if not answered_by_codex(probe):
        log("Codex antwortet noch nicht selbst — nächster Versuch in einer Stunde")
        return 0

    updated = restored_config(CONFIG.read_text())
    if updated is None:
        notify("Codex ist zurück", "Die Hermes-Konfiguration wurde inzwischen geändert, ich habe sie nicht angefasst.")
        finish()
        return 1
    shutil.copy2(CONFIG, CONFIG.with_name(f"config.yaml.bak.restore.{now:%Y%m%d_%H%M%S}"))
    CONFIG.write_text(updated)
    log("config.yaml: Hauptmodell wieder gpt-5.6-luna (openai-codex), Ersatz poolside")
    time.sleep(5)   # the gateway picks config changes up without a restart

    moved = repin(pinned_sessions())
    log(f"{moved} Gespräche auf gpt-5.6-luna umgestellt")

    if answered_by_codex(new_session("model-restore: Kontrolle")):
        notify("JARVIS denkt wieder mit gpt-5.6-luna",
               f"Das ChatGPT-Kontingent ist zurück; {moved} Gespräche umgestellt.")
    else:
        notify("Hauptmodell umgestellt, aber unbestätigt",
               "Die Konfiguration steht auf gpt-5.6-luna, eine neue Sitzung landete aber nicht bei Codex.")
    finish()
    return 0


if __name__ == "__main__":
    sys.exit(main())
