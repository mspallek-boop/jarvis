"""Hermes handler that reads the phone's health snapshot written by the bridge."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

HEALTH_STATE = Path(os.environ.get("JARVIS_HEALTH_STATE", str(Path.home() / ".hermes" / "jarvis-health.json")))


def _age(received_at: float) -> str:
    if not received_at:
        return "Zeitpunkt unbekannt"
    delta = max(0, int(time.time() - received_at))
    if delta < 90:
        return "gerade eben"
    if delta < 3600:
        return f"vor {delta // 60} Min"
    if delta < 86400:
        return f"vor {delta // 3600} Std"
    return f"vor {delta // 86400} Tagen"


def health_today(args: dict[str, Any], **kwargs: Any) -> str:
    """Return the phone's latest steps, active energy and glucose, or say plainly
    that no snapshot has arrived yet. Read-only; never fabricates a value."""
    try:
        record = json.loads(HEALTH_STATE.read_text())
    except (OSError, ValueError):
        return json.dumps({
            "ok": False,
            "error": "Noch keine Health-Daten vom iPhone. In der App unter Einstellungen → Gesundheit den Zugriff erlauben.",
        }, ensure_ascii=False)
    if not isinstance(record, dict):
        return json.dumps({"ok": False, "error": "Health-Daten unlesbar."}, ensure_ascii=False)

    out = {
        "ok": True,
        "steps": record.get("steps"),
        "active_energy_kcal": record.get("active_energy_kcal"),
        "glucose_mgdl": record.get("glucose_mgdl"),
        "updated": _age(float(record.get("received_at") or 0)),
    }
    return json.dumps(out, ensure_ascii=False)
