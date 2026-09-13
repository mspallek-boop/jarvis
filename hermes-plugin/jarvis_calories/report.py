"""Plain-text reports for the local JARVIS nutrition diary.

The report is a clean, sectioned WhatsApp message: a headline with the calorie
balance, a macro block, an optional activity block, and finally a bullet list of
everything eaten and drunk that day. It uses WhatsApp's ``*bold*`` markup and one
item per line rather than a monospaced table, so it stays legible on a phone.
"""

from __future__ import annotations

from datetime import date
from typing import Any


WEEKDAYS_SHORT = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")


def _number(value: Any, unit: str) -> str:
    if value is None:
        return "nicht erfasst"
    value = float(value)
    rendered = f"{value:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{rendered.rstrip('0').rstrip(',')} {unit}".rstrip()


def _integer(value: Any, unit: str) -> str:
    if value is None:
        return "nicht erfasst"
    rendered = f"{int(round(float(value))):,}".replace(",", ".")
    return f"{rendered} {unit}".rstrip()


def _date_short(value: str) -> str:
    day = date.fromisoformat(value)
    return f"{WEEKDAYS_SHORT[day.weekday()]} {day.day:02d}.{day.month:02d}.{day.year}"


def _calorie_line(summary: dict[str, Any]) -> str:
    total = summary.get("total_calories")
    target = summary.get("target_calories")
    remaining = summary.get("remaining_calories")
    if total is not None and target is not None:
        line = f"*{_integer(total, '')}* / {_integer(target, '')} kcal"
        if remaining is not None:
            if remaining >= 0:
                line += f"   ✅ {_integer(remaining, '')} übrig"
            else:
                line += f"   ⚠️ {_integer(-remaining, '')} über Ziel"
        return line
    if total is not None:
        return f"*{_integer(total, 'kcal')}*"
    return "Kalorien nicht erfasst"


def format_daily_balance(summary: dict[str, Any]) -> str:
    """Render one API day summary as a ready-to-send WhatsApp message."""
    sections = [
        f"🍽️ *Tagesbilanz · {_date_short(str(summary['date']))}*",
        _calorie_line(summary),
    ]

    macros = [
        f"🥩 Eiweiß {_number(summary.get('total_protein_g'), 'g')}",
        f"🍞 KH {_number(summary.get('total_carbohydrates_g'), 'g')}",
        f"🧈 Fett {_number(summary.get('total_fat_g'), 'g')}",
        f"🍬 Zucker {_number(summary.get('total_sugar_g'), 'g')}",
    ]
    sections.append("*Makros*\n" + "\n".join(macros))

    activity: list[str] = []
    if summary.get("activity_calories") is not None:
        line = f"🔥 Aktivität {_integer(summary['activity_calories'], 'kcal')}"
        if summary.get("net_calories") is not None:
            line += f" · Netto {_integer(summary['net_calories'], 'kcal')}"
        activity.append(line)
    if summary.get("steps") is not None:
        activity.append(f"👟 {_integer(summary['steps'], 'Schritte')}")
    if activity:
        sections.append("*Aktivität*\n" + "\n".join(activity))

    entries = summary.get("entries") or []
    bullets = [
        f"• {str(entry.get('description', '')).strip()}"
        for entry in entries
        if str(entry.get("description", "")).strip()
    ]
    if bullets:
        sections.append(f"*Erfasst ({len(entries)})*\n" + "\n".join(bullets))
    else:
        sections.append("*Erfasst (0)*\nkeine Lebensmittel oder Getränke")

    return "\n\n".join(sections)
