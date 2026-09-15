"""Hermes tool schemas for the local calorie tracker."""

CALORIES_LOG = {
    "name": "calories_log",
    "description": (
        "Persist a food or drink calorie entry in the user's local JARVIS calorie diary. "
        "Use this whenever the user says they ate, drank, or wants to log calories. "
        "Ask for calories if they did not give or clearly imply an amount; never invent them."
    ),
    "parameters": {"type": "object", "properties": {
        "calories": {"type": "integer", "description": "Positive calorie amount"},
        "description": {"type": "string", "description": "Food or drink, e.g. Greek yogurt"},
        "meal": {"type": "string", "description": "Optional meal such as breakfast, lunch, dinner, snack"},
        "sugar_g": {"type": "number", "description": "Optional sugar content in grams, if known"},
        "protein_g": {"type": "number", "description": "Optional protein content in grams, if known"},
        "fat_g": {"type": "number", "description": "Optional fat content in grams, if known"},
        "carbohydrates_g": {"type": "number", "description": "Optional carbohydrate content in grams, if known"},
        "occurred_at": {"type": "string", "description": "Optional ISO-8601 timestamp; omit for now"},
    }, "required": ["calories", "description"]},
}

CALORIES_DAILY = {
    "name": "calories_daily_summary",
    "description": "Read the local calorie diary for one calendar day: entries, and for every nutrient the Ist next to the Soll derived from the goal (nutrients list with status ok/over/under/incomplete).",
    "parameters": {"type": "object", "properties": {
        "date": {"type": "string", "description": "ISO date YYYY-MM-DD; omit for today"},
    }},
}

CALORIES_DAILY_REPORT = {
    "name": "calories_daily_report",
    "description": (
        "Generate the ready-to-send daily nutrition balance in German. Use it for the evening daily "
        "report, then send its output exactly as returned: it already has the date, a plain-text "
        "WhatsApp-readable table, separate status badges, and every recorded food/drink. Do not "
        "reformat it into prose or add emoji."
    ),
    "parameters": {"type": "object", "properties": {
        "date": {"type": "string", "description": "ISO date YYYY-MM-DD; omit for today"},
    }},
}

CALORIES_WEEKLY = {
    "name": "calories_weekly_summary",
    "description": "Read a Monday-to-Sunday calorie summary for a requested week from the local diary.",
    "parameters": {"type": "object", "properties": {
        "week_start": {"type": "string", "description": "Any ISO date in the requested week; omit for current week"},
    }},
}

CALORIES_PROGRESS = {
    "name": "calories_progress",
    "description": "Show calorie and optional weekly check-in progress across multiple weeks from the local diary.",
    "parameters": {"type": "object", "properties": {
        "weeks": {"type": "integer", "description": "Weeks to return, 1 to 52; default 8"},
        "ending_on": {"type": "string", "description": "Optional ISO date ending the range"},
    }},
}

CALORIES_GOAL = {
    "name": "calories_set_goal",
    "description": (
        "Set or change the user's daily goal from a date onward: the calorie target and, optionally, "
        "the goal body weight. The Soll for protein, carbohydrates, fat and sugar is derived from these "
        "two values automatically; never set nutrient targets by hand."
    ),
    "parameters": {"type": "object", "properties": {
        "daily_calories": {"type": "integer", "description": "Positive daily calorie target"},
        "goal_weight_kg": {"type": "number", "description": "Optional goal body weight in kg; omit to keep the current one"},
        "effective_from": {"type": "string", "description": "Optional ISO date; default today"},
    }, "required": ["daily_calories"]},
}

CALORIES_CHECKIN = {
    "name": "calories_weekly_checkin",
    "description": "Save a weekly local progress note and optional weight measurement. Use for an explicit weekly check-in, never infer a weight.",
    "parameters": {"type": "object", "properties": {
        "week_start": {"type": "string", "description": "Optional ISO date in the check-in week; default current week"},
        "weight_kg": {"type": "number", "description": "Optional measured body weight in kilograms"},
        "note": {"type": "string", "description": "Optional progress/reflection note"},
    }},
}
