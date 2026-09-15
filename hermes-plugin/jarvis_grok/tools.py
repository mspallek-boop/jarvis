"""Hermes handlers that enqueue/read the Grok file-queue bridge."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

HOME = Path.home()
# Prefer the live repo module; fall back to a copy under ~/.hermes/services if present.
_CANDIDATES = [
    Path(os.environ.get("JARVIS_GROK_QUEUE", "")),
    HOME / "Documents/JARVIS/bridge",
    HOME / ".hermes/services",
]


def _load_queue():
    for base in _CANDIDATES:
        if not base or not (base / "grok_queue.py").exists():
            continue
        if str(base) not in sys.path:
            sys.path.insert(0, str(base))
        import grok_queue  # type: ignore
        return grok_queue
    raise FileNotFoundError("grok_queue.py not found")


def grok_delegate(args: dict[str, Any], **kwargs: Any) -> str:
    args = args if isinstance(args, dict) else {}
    task = str(args.get("task") or "").strip()
    if not task:
        return json.dumps({"ok": False, "error": "task fehlt"}, ensure_ascii=False)
    target = str(args.get("target") or "Botschaft Jarvis").strip() or "Botschaft Jarvis"
    priority = str(args.get("priority") or "normal").strip() or "normal"
    dry_run = bool(args.get("dry_run", False))
    try:
        gq = _load_queue()
        out = gq.enqueue_task(task, target=target, priority=priority, dry_run=dry_run)
    except Exception as exc:  # noqa: BLE001 — surface to Hermes as JSON
        return json.dumps({"ok": False, "error": str(exc)[:240]}, ensure_ascii=False)
    return json.dumps({"ok": True, **out}, ensure_ascii=False)


def grok_delegate_status(args: dict[str, Any], **kwargs: Any) -> str:
    args = args if isinstance(args, dict) else {}
    job_id = str(args.get("id") or "").strip()
    if not job_id:
        return json.dumps({"ok": False, "error": "id fehlt"}, ensure_ascii=False)
    try:
        gq = _load_queue()
        result = gq.read_result(job_id)
    except Exception as exc:  # noqa: BLE001
        return json.dumps({"ok": False, "error": str(exc)[:240]}, ensure_ascii=False)
    if result is None:
        return json.dumps({"ok": True, "pending": True, "id": job_id}, ensure_ascii=False)
    return json.dumps({"ok": True, "pending": False, "result": result}, ensure_ascii=False)
