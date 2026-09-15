#!/usr/bin/env python3
"""File-queue client for Jarvis ↔ Grok Bot (no webhook / no secrets).

Layout under ~/.hermes/grok-queue/:
  inbox/       Jarvis drops {id,task,target,priority,dry_run}
  processing/  optional in-flight
  outbox/      results {id,status,summary,result}

Atomic writes: write *.tmp then os.replace to *.json.

Targets: Default Admin; Bridge-Delegation auch an "Botschaft Jarvis".
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import time
from pathlib import Path
from typing import Optional

DEFAULT_ROOT = Path.home() / ".hermes" / "grok-queue"
JOB_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")
TARGET_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_ -]{0,63}")
PRIORITIES = {"low", "normal", "high"}
STATUSES = {"ok", "error", "needs_approval"}
# Known bridge targets (others still allowed if they match TARGET_RE).
KNOWN_TARGETS = (
    "Admin",
    "Botschaft Jarvis",
)
DEFAULT_TARGET = "Admin"
MAX_TASK_CHARS = 4000


def queue_dirs(root: Path = DEFAULT_ROOT) -> dict:
    root = Path(root).expanduser()
    dirs = {
        "root": root,
        "inbox": root / "inbox",
        "outbox": root / "outbox",
        "processing": root / "processing",
    }
    for path in dirs.values():
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return dirs


def new_job_id() -> str:
    return f"grok-{secrets.token_hex(8)}"


def _atomic_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(path)


def enqueue_task(
    task: str,
    target: str = DEFAULT_TARGET,
    priority: str = "normal",
    dry_run: bool = False,
    job_id: str = "",
    root: Path = DEFAULT_ROOT,
) -> dict:
    """Write one task JSON into inbox/. Returns the task record."""
    if not isinstance(task, str) or not 1 <= len(task) <= MAX_TASK_CHARS:
        raise ValueError(f"task muss 1 bis {MAX_TASK_CHARS} Zeichen haben")
    if not TARGET_RE.fullmatch(target or ""):
        raise ValueError("Ungültiges target")
    if priority not in PRIORITIES:
        raise ValueError("Ungültige priority")
    job_id = job_id or new_job_id()
    if not JOB_ID_RE.fullmatch(job_id):
        raise ValueError("Ungültige id")

    dirs = queue_dirs(root)
    record = {
        "id": job_id,
        "task": task,
        "target": target,
        "priority": priority,
        "dry_run": bool(dry_run),
        "enqueued_at": time.time(),
    }
    path = dirs["inbox"] / f"{job_id}.json"
    if path.exists():
        raise FileExistsError(f"Task existiert schon: {job_id}")
    _atomic_write(path, record)

    if dry_run:
        # Immediate local ACK so Jarvis can verify the pipe without Admin.
        ack = {
            "id": job_id,
            "status": "ok",
            "summary": "dry_run ack",
            "result": {"dry_run": True, "accepted": True},
            "acked_at": time.time(),
        }
        _atomic_write(dirs["outbox"] / f"{job_id}.json", ack)
        # Move inbox → processing then drop (or leave processing stamp)
        processing = dirs["processing"] / f"{job_id}.json"
        _atomic_write(processing, {**record, "status": "dry_run_acked"})
        try:
            path.unlink(missing_ok=True)
        except TypeError:
            if path.exists():
                path.unlink()
        return {"task": record, "result": ack, "dry_run_acked": True}

    return {"task": record, "path": str(path), "dry_run_acked": False}


def read_result(job_id: str, root: Path = DEFAULT_ROOT) -> Optional[dict]:
    if not JOB_ID_RE.fullmatch(job_id or ""):
        raise ValueError("Ungültige id")
    dirs = queue_dirs(root)
    path = dirs["outbox"] / f"{job_id}.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else None


def write_result(
    job_id: str,
    status: str,
    summary: str,
    result: Optional[dict] = None,
    root: Path = DEFAULT_ROOT,
) -> dict:
    """Grok/Admin side: drop a result into outbox/."""
    if not JOB_ID_RE.fullmatch(job_id or ""):
        raise ValueError("Ungültige id")
    if status not in STATUSES:
        raise ValueError("Ungültiger status")
    if not isinstance(summary, str):
        raise ValueError("Ungültige summary")
    payload = {
        "id": job_id,
        "status": status,
        "summary": summary,
        "result": result if isinstance(result, dict) else {},
        "written_at": time.time(),
    }
    dirs = queue_dirs(root)
    _atomic_write(dirs["outbox"] / f"{job_id}.json", payload)
    return payload


def list_inbox(root: Path = DEFAULT_ROOT) -> list:
    dirs = queue_dirs(root)
    jobs = []
    for path in sorted(dirs["inbox"].glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                jobs.append(data)
        except (OSError, json.JSONDecodeError):
            continue
    return jobs


def main() -> None:
    parser = argparse.ArgumentParser(description="Jarvis↔Grok file queue")
    sub = parser.add_subparsers(dest="cmd", required=True)

    enq = sub.add_parser("enqueue", help="Task in inbox legen")
    enq.add_argument("task")
    enq.add_argument("--target", default=DEFAULT_TARGET,
                    help=f"Ziel-Bot (z.B. Admin, \"Botschaft Jarvis\"); known={list(KNOWN_TARGETS)}")
    enq.add_argument("--priority", default="normal", choices=sorted(PRIORITIES))
    enq.add_argument("--dry-run", action="store_true")
    enq.add_argument("--id", default="")

    rd = sub.add_parser("result", help="Ergebnis aus outbox lesen")
    rd.add_argument("id")

    sub.add_parser("inbox", help="Inbox auflisten")
    sub.add_parser("init", help="Ordner anlegen")

    args = parser.parse_args()
    if args.cmd == "init":
        dirs = queue_dirs()
        print(json.dumps({k: str(v) for k, v in dirs.items()}, indent=2))
        return
    if args.cmd == "enqueue":
        out = enqueue_task(args.task, target=args.target, priority=args.priority,
                           dry_run=args.dry_run, job_id=args.id or "")
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return
    if args.cmd == "result":
        print(json.dumps(read_result(args.id), indent=2, ensure_ascii=False))
        return
    if args.cmd == "inbox":
        print(json.dumps(list_inbox(), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
