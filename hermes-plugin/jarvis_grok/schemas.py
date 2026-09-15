"""Hermes tool schemas for delegating work to Botschaft Jarvis via file queue."""

GROK_DELEGATE = {
    "name": "grok_delegate",
    "description": (
        "Delegate a task to Botschaft Jarvis (Grok Bot embassy) over the local file queue "
        "at ~/.hermes/grok-queue. Default target is \"Botschaft Jarvis\". Use this when the "
        "user wants Jarvis to hand work to Botschaft Jarvis / the Grok bots. "
        "For a pipe check, set dry_run true — that only writes an immediate outbox ACK and "
        "does not execute. Live work: dry_run false, then poll with grok_delegate_status. "
        "No webhook, no secrets. Returns a job id."
    ),
    "parameters": {"type": "object", "properties": {
        "task": {"type": "string", "description": "Self-contained task for Botschaft Jarvis"},
        "target": {"type": "string", "description": "Usually \"Botschaft Jarvis\" (default) or Admin"},
        "priority": {"type": "string", "description": "low | normal | high; default normal"},
        "dry_run": {"type": "boolean", "description": "If true, only ACK the pipe; do not execute"},
    }, "required": ["task"]},
}

GROK_DELEGATE_STATUS = {
    "name": "grok_delegate_status",
    "description": (
        "Read the outbox result for a job created with grok_delegate. Returns status, summary "
        "and result when ready, or pending if still waiting."
    ),
    "parameters": {"type": "object", "properties": {
        "id": {"type": "string", "description": "The job id grok_delegate returned"},
    }, "required": ["id"]},
}
