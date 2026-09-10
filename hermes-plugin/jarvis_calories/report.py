"""Plain-text reports for the local JARVIS nutrition diary.

The report deliberately uses a compact text table rather than Markdown table
syntax. It stays legible in WhatsApp and can be sent without an LLM reflowing
the food list into a wall of prose.
"""

from __future__ import annotations

from datetime import date
from typing import Any


WEEKDAYS = ("Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag")
MONTHS = ("Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember")


def _number(value: Any, unit: str) -> str:
    if value is None:
        return "nicht erfasst"
    value = float(value)
    rendered = f"{value:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{rendered.rstrip('0').rstrip(',')} {unit}"


def _integer(value: Any, unit: str) -> str:
    if value is None:
        return "nicht erfasst"
    rendered = f"{int(round(float(value))):,}".replace(",", ".")
    return f"{rendered} {unit}".rstrip()


def _date_heading(value: str) -> str:
    day = date.fromisoformat(value)
    return f"{WEEKDAYS[day.weekday()]}, {day.day}. {MONTHS[day.month - 1]} {day.year}"


def _row(label: str, value: str) -> str:
    return f"{label:<16} {value}"


def _badges(summary: dict[str, Any]) -> list[str]:
    badges: list[str] = []
    target = summary.get("target_calories")
    remaining = summary.get("remaining_calories")
    if target is not None and remaining is not None:
        state = "IM RAHMEN" if remaining >= 0 else "ÜBER ZIEL"
        badges.append(f"[KALORIENZIEL: {state}]")
    macros = ("total_protein_g", "total_fat_g", "total_carbohydrates_g", "total_sugar_g")
    recorded = sum(summary.get(field) is not None for field in macros)
    if recorded:
        state = "VOLLSTÄNDIG" if recorded == len(macros) else "TEILWEISE ERFASST"
        badges.append(f"[NÄHRWERTE: {state}]")
    if summary.get("activity_calories") is not None or summary.get("steps") is not None:
        badges.append("[AKTIVITÄT ERFASST]")
    return badges


def format_daily_balance(summary: dict[str, Any]) -> str:
    """Render one API day summary as a ready-to-send WhatsApp message."""
    rows = [
        _row("Kalorien", _integer(summary.get("total_calories"), "kcal")),
        _row("Kalorienziel", _integer(summary.get("target_calories"), "kcal")),
        _row("Rest zum Ziel", _integer(summary.get("remaining_calories"), "kcal")),
        _row("Eiweiß", _number(summary.get("total_protein_g"), "g")),
        _row("Kohlenhydrate", _number(summary.get("total_carbohydrates_g"), "g")),
        _row("Fett", _number(summary.get("total_fat_g"), "g")),
        _row("Zucker", _number(summary.get("total_sugar_g"), "g")),
    ]
    if summary.get("activity_calories") is not None:
        rows.append(_row("Aktivität", _integer(summary["activity_calories"], "kcal")))
        rows.append(_row("Netto-Kalorien", _integer(summary.get("net_calories"), "kcal")))
    if summary.get("steps") is not None:
        rows.append(_row("Schritte", _integer(summary["steps"], "")))

    entries = summary.get("entries") or []
    foods = "; ".join(str(entry.get("description", "")).strip() for entry in entries if entry.get("description"))
    food_paragraph = f"Erfasst ({len(entries)}): {foods or 'keine Lebensmittel oder Getränke'}"
    # WhatsApp renders this block monospaced, keeping the two columns aligned
    # instead of turning a small mobile screen into a ragged paragraph.
    table = "```\n" + "\n".join(["Wert             Heute", "-------------------------", *rows]) + "\n```"
    sections = [f"*Tagesbilanz – {_date_heading(str(summary['date']))}*", table]
    badges = _badges(summary)
    if badges:
        sections.append("\n".join(badges))
    sections.append(food_paragraph)
    return "\n\n".join(sections)
