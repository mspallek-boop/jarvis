"""Hermes tool schemas for phone calls placed on the user's behalf."""

PHONE_CALL = {
    "name": "phone_call",
    "description": (
        "Place a real phone call in the user's name: the user's Fairytel line dials the number and a "
        "realtime voice holds the whole conversation from your task alone, says it is an AI, hangs up, "
        "and the result arrives in the app via jarvis-notify. It costs money and reaches real people. "
        "Call ONLY after the user confirmed, in this conversation, the exact number, who it is, and the "
        "task including what may be agreed; show them and wait for a clear yes. Returns at once with a "
        "call_id; the call runs in the background. Emergency, premium and non-AT/DE numbers are refused."
    ),
    "parameters": {"type": "object", "properties": {
        "to": {"type": "string", "description": "Phone number, e.g. 0664 1234567 or +49 30 1234567"},
        "callee": {"type": "string", "description": "Who is called, e.g. 'Friseur Haarmonie' or 'Ordination Dr. Huber'"},
        "task": {"type": "string", "description": (
            "Self-contained briefing in German for the voice, which knows nothing else: the goal; which "
            "facts about the user it may share (name, preferred times); what it may agree to; what it must "
            "not agree to; what to do if the goal is impossible; whether to leave a voicemail.")},
        "max_minutes": {"type": "integer", "description": "Hard time cap in minutes, 1-15; default 6"},
    }, "required": ["to", "callee", "task"]},
}

PHONE_CALL_STATUS = {
    "name": "phone_call_status",
    "description": (
        "Read the state of a phone call placed with phone_call: status, outcome, summary and transcript. "
        "Omit call_id for the most recent call. Report failures honestly (busy, no answer, refused)."
    ),
    "parameters": {"type": "object", "properties": {
        "call_id": {"type": "string", "description": "The call_id phone_call returned; omit for the latest"},
    }},
}
