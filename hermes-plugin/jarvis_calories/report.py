"""Plain-text reports for the local JARVIS nutrition diary.

The report is a clean, sectioned WhatsApp message: a headline, every nutrient
with its Ist next to the Soll derived from the goal plus a verdict, an optional
activity block, and finally a bullet list of everything eaten and drunk that day. It uses WhatsApp's ``*bold*`` markup and one
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


EMOJI = {"calories": "🔥", "protein_g": "🥩", "carbohydrates_g": "🍞", "fat_g": "🧈", "sugar_g": "🍬"}


def _amount(value: Any, unit: str) -> str:
    return _integer(value, unit) if unit == "kcal" else _number(value, unit)


def _nutrient_line(row: dict[str, Any]) -> str:
    """One nutrient as "Ist / Soll" plus a verdict, e.g. Eiweiß: *116* / mind. 140 g ⚠️ 24 g fehlen."""
    unit, actual, target = row["unit"], row.get("actual"), row.get("target")
    bound = "mind." if row.get("limit") == "min" else "max."
    ist = f"*{_amount(actual, '')}*" if actual is not None else "nicht erfasst"
    line = f"{EMOJI.get(row['key'], '•')} {row['label']}: {ist}"
    if target is None:
        return f"{line} {unit} · kein Soll" if actual is not None else line
    line += f" / {bound} {_amount(target, unit)}"
    status = row.get("status")
    if status == "ok":
        gap = target - actual
        line += f"  ✅ {_amount(gap, unit)} übrig" if row.get("limit") == "max" and gap > 0 else "  ✅"
    elif status == "over":
        line += f"  ⚠️ {_amount(actual - target, unit)} zu viel"
    elif status == "under":
        line += f"  ⚠️ {_amount(target - actual, unit)} fehlen"
    elif status == "incomplete":
        line += "  ❔ unvollständig"
    return line


def _verdict(rows: list[dict[str, Any]]) -> str | None:
    judged = [row for row in rows if row.get("status") is not None]
    if not judged:
        return None
    off = [row["label"] for row in judged if row["status"] in ("over", "under")]
    open_ = [row["label"] for row in judged if row["status"] == "incomplete"]
    if off:
        verdict = f"⚠️ Daneben: {', '.join(off)}"
    elif open_:
        verdict = "✅ Bisher im Soll"
    else:
        verdict = "✅ Alles im Soll — gut gegessen"
    if open_:
        verdict += f"\n❔ Nicht bei allen Einträgen erfasst: {', '.join(open_)}"
    return verdict


def format_daily_balance(summary: dict[str, Any]) -> str:
    """Render one API day summary as a ready-to-send WhatsApp message."""
    sections = [f"🍽️ *Tagesbilanz · {_date_short(str(summary['date']))}*"]

    rows = summary.get("nutrients") or []
    lines = [_nutrient_line(row) for row in rows] or ["Nährwerte nicht verfügbar"]
    block = "*Nährwerte · Ist / Soll*\n" + "\n".join(lines)
    verdict = _verdict(rows)
    if verdict:
        block += "\n\n" + verdict
    targets = summary.get("targets")
    if targets:
        basis = f"{_integer(targets['calories'], 'kcal')}/Tag"
        if summary.get("goal_weight_kg"):
            basis += f" · Zielgewicht {_number(summary['goal_weight_kg'], 'kg')}"
        block += f"\n_Soll aus deinem Ziel: {basis}_"
    else:
        block += "\n_Kein Ziel gesetzt — deshalb kein Soll._"
    sections.append(block)

    activity: list[str] = []
    if summary.get("activity_calories") is not None:
        line = f"🏃 Aktivität {_integer(summary['activity_calories'], 'kcal')}"
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
