"""Which numbers JARVIS may call, how often, and how the provider wants them dialled.

These rules are enforced in code, not only in the model's instructions: a call
to a premium or emergency number, or an eleventh call in a day, is refused
before any SIP traffic happens.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path


class PolicyError(ValueError):
    """A call the user must not be charged for or must not happen."""


ALLOWED_COUNTRIES = tuple(
    c.strip() for c in os.environ.get("PHONE_ALLOWED_COUNTRIES", "43,49").split(",") if c.strip()
)

# Premium, shared-cost and directory ranges that can cost far more than the
# 3.9 ct/min a normal Austrian call costs. Freephone (0800) stays allowed.
BLOCKED_PREFIXES = (
    "43900", "43901", "43930", "43931", "43939",  # AT Mehrwertdienste
    "43810", "43820", "43821",                    # AT tarifierte Servicenummern
    "43118",                                      # AT Auskunftsdienste
    "49900", "49137", "49118", "49180", "4912",   # DE Premium, Massenverkehr, Auskunft, Service
    "49191", "49192", "49193", "49194",           # DE Online-Dienste
    "4970",                                       # DE persönliche Rufnummern (Fairytel: 0,30 €/min)
)

# Emergency and short codes are shorter than any subscriber number, so a
# minimum length catches 112, 133, 144, 116xxx and friends in one rule.
MIN_DIGITS = 8
MAX_DIGITS = 15

MAX_PER_DAY = int(os.environ.get("PHONE_MAX_CALLS_PER_DAY", "5"))
MAX_PER_MONTH = int(os.environ.get("PHONE_MAX_CALLS_PER_MONTH", "20"))
DEFAULT_MINUTES = 6
MAX_MINUTES = 15


def normalize(raw: str) -> str:
    """Any common way of writing a number -> E.164 ('+43664...').

    A number without country code is read as Austrian, because that is where
    the user lives; one without any leading zero is refused rather than guessed.
    """
    s = re.sub(r"[\s\-/().]", "", str(raw or ""))
    if s.startswith("+"):
        digits = s[1:]
    elif s.startswith("00"):
        digits = s[2:]
    elif s.startswith("0"):
        digits = "43" + s[1:]
    else:
        raise PolicyError("Bitte die Nummer mit Vorwahl angeben, z. B. 0664 1234567 oder +49 30 1234567.")
    if not digits.isdigit():
        raise PolicyError("Die Nummer enthält Zeichen, die keine Ziffern sind.")
    return "+" + digits


def check_number(e164: str) -> None:
    digits = e164.lstrip("+")
    if not MIN_DIGITS <= len(digits) <= MAX_DIGITS:
        raise PolicyError("Kurz- und Notrufnummern ruft JARVIS nicht an; die Nummer ist zu kurz oder zu lang.")
    if not digits.startswith(ALLOWED_COUNTRIES):
        raise PolicyError("JARVIS ruft nur Nummern in Österreich und Deutschland an.")
    if digits.startswith(BLOCKED_PREFIXES):
        raise PolicyError("Mehrwert-, Service- und Auskunftsnummern ruft JARVIS nicht an.")


def dial_string(e164: str, fmt: str = "national") -> str:
    """What goes into the Request-URI. Austrian numbers national, others with 00."""
    digits = e164.lstrip("+")
    if fmt == "e164":
        return "+" + digits
    if fmt == "national" and digits.startswith("43"):
        return "0" + digits[2:]
    return "00" + digits


def clamp_minutes(value) -> int:
    try:
        minutes = int(value)
    except (TypeError, ValueError):
        minutes = DEFAULT_MINUTES
    return max(1, min(MAX_MINUTES, minutes))


def check_limits(calls_dir: Path, now: datetime | None = None) -> None:
    """Refuse a call beyond the daily or monthly cap; failed dials count too."""
    now = now or datetime.now()
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = day_start.replace(day=1)
    today = month = 0
    for path in calls_dir.glob("*.json") if calls_dir.is_dir() else ():
        try:
            created = datetime.fromisoformat(json.loads(path.read_text())["created_at"])
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if created >= month_start:
            month += 1
        if created >= day_start:
            today += 1
    if today >= MAX_PER_DAY:
        raise PolicyError(f"Heute wurden schon {today} Anrufe gestartet; das Tageslimit ist {MAX_PER_DAY}.")
    if month >= MAX_PER_MONTH:
        raise PolicyError(f"Diesen Monat wurden schon {month} Anrufe gestartet; das Limit ist {MAX_PER_MONTH}.")


def stale(created_at: str, minutes: int, now: datetime | None = None) -> bool:
    """A 'running' record older than its own time cap plus slack is a dead process."""
    try:
        created = datetime.fromisoformat(created_at)
    except (TypeError, ValueError):
        return True
    return (now or datetime.now()) - created > timedelta(minutes=minutes + 3)
