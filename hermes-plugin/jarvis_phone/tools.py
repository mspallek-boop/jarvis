"""Hermes handlers that hand phone calls to the standalone phone module.

The call itself runs in its own Python (phone venv) and process group, so a
long conversation never blocks a Hermes turn and a Hermes restart never cuts
a call. The task travels on stdin, not in argv, so it is not visible in `ps`.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

HOME = Path.home()
PHONE_CODE = Path(os.environ.get("JARVIS_PHONE_CODE", HOME / ".hermes/services/phone"))
PHONE_PYTHON = os.environ.get(
    "JARVIS_PHONE_PYTHON", str(HOME / "Developer/JARVIS/LocalData/Runtime/phone-venv/bin/python"))


def _run(argv: list[str], stdin: str = "") -> str:
    try:
        proc = subprocess.run([PHONE_PYTHON, str(PHONE_CODE / "call.py"), *argv], input=stdin,
                              capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return json.dumps({"ok": False, "error": "Das Telefonmodul ist nicht erreichbar."})
    return proc.stdout.strip() or json.dumps({"ok": False, "error": "Das Telefonmodul hat nicht geantwortet."})


def phone_call(args: dict[str, Any], **kwargs: Any) -> str:
    args = args if isinstance(args, dict) else {}
    argv = ["start", "--to", str(args.get("to", "")), "--callee", str(args.get("callee", "")),
            "--minutes", str(args.get("max_minutes") or 6)]
    return _run(argv, stdin=str(args.get("task", "")))


def phone_call_status(args: dict[str, Any], **kwargs: Any) -> str:
    args = args if isinstance(args, dict) else {}
    call_id = str(args.get("call_id") or "").strip()
    return _run(["status"] + (["--id", call_id] if call_id else []))
