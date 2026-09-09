"""Hermes handlers for the JARVIS server's local calorie API."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from typing import Any


CALORIES_URL = os.environ.get("JARVIS_CALORIES_URL", "http://127.0.0.1:8765/api/calories")


def _request(path: str, method: str = "GET", payload: dict[str, Any] | None = None) -> str:
    token = os.environ.get("JARVIS_HUD_TOKEN", "")
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        f"{CALORIES_URL.rstrip('/')}{path}", data=data, method=method,
        headers={"Content-Type": "application/json", "X-Jarvis-Token": token},
    )
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            return response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8")).get("error")
        except Exception:
            detail = None
        return json.dumps({"ok": False, "error": detail or "Calorie request was rejected."})
    except Exception:
        return json.dumps({"ok": False, "error": "Local calorie tracker is unreachable."})


def calories_log(args: dict[str, Any], **kwargs: Any) -> str:
    return _request("/entries", "POST", args if isinstance(args, dict) else {})


def calories_daily_summary(args: dict[str, Any], **kwargs: Any) -> str:
    day = args.get("date") if isinstance(args, dict) else None
    return _request(f"/days/{urllib.parse.quote(str(day), safe='')}" if day else f"/days/{date.today().isoformat()}")


def calories_weekly_summary(args: dict[str, Any], **kwargs: Any) -> str:
    day = args.get("week_start") if isinstance(args, dict) else None
    return _request(f"/weeks/{urllib.parse.quote(str(day), safe='')}" if day else f"/weeks/{date.today().isoformat()}")


def calories_progress(args: dict[str, Any], **kwargs: Any) -> str:
    args = args if isinstance(args, dict) else {}
    params: dict[str, Any] = {}
    if args.get("weeks") is not None:
        params["weeks"] = args["weeks"]
    if args.get("ending_on"):
        params["ending_on"] = args["ending_on"]
    return _request("/progress" + ("?" + urllib.parse.urlencode(params) if params else ""))


def calories_set_goal(args: dict[str, Any], **kwargs: Any) -> str:
    return _request("/goal", "PUT", args if isinstance(args, dict) else {})


def calories_weekly_checkin(args: dict[str, Any], **kwargs: Any) -> str:
    return _request("/checkins", "POST", args if isinstance(args, dict) else {})
