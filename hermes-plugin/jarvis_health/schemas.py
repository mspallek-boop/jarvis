"""Hermes tool schema for the phone's health snapshot."""

HEALTH_TODAY = {
    "name": "health_today",
    "description": (
        "Read the latest Apple Health snapshot the user's iPhone sent: today's step count, "
        "today's active energy in kilocalories, and the most recent blood-glucose reading. "
        "Use it whenever the user asks about their steps, activity, movement, calories burned, "
        "or blood sugar. The numbers come from the phone; if a value is missing the user has "
        "either not granted that type in Health or has no data for it yet. Never invent values."
    ),
    "parameters": {"type": "object", "properties": {}},
}
