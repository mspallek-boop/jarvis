"""Read-only Gmail access through the locally configured Himalaya CLI.

This plugin deliberately exposes only envelope listing and searching.  Sending
mail is an externally visible side effect and JARVIS has no email-specific
confirmation contract yet, so it must not be reachable through this tool.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
from typing import Any, Optional, Tuple


DEFAULT_CONFIG = Path.home() / "Library" / "Application Support" / "himalaya" / "config.toml"
HIMALAYA_CONFIG = Path(os.environ.get("JARVIS_HIMALAYA_CONFIG", str(DEFAULT_CONFIG))).expanduser()
HIMALAYA_ACCOUNT = os.environ.get("JARVIS_HIMALAYA_ACCOUNT", "gmail")
HIMALAYA_BIN = os.environ.get("JARVIS_HIMALAYA_BIN", "himalaya")
MAX_LIMIT = 20
COMMAND_TIMEOUT_SECONDS = 20


def _error(message: str) -> str:
    """Return a deliberately generic error, never CLI stderr or config details."""
    return json.dumps({"ok": False, "error": message})


def _clean_text(value: Any, maximum: int) -> str:
    """Bound untrusted envelope metadata before giving it to the agent."""
    if not isinstance(value, str):
        return ""
    value = " ".join(value.split())
    return value[:maximum]


def _addresses(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    addresses = []
    for item in value[:10]:
        if not isinstance(item, dict):
            continue
        address = {
            "email": _clean_text(item.get("email"), 254),
            "name": _clean_text(item.get("name"), 160),
        }
        if address["email"] or address["name"]:
            addresses.append(address)
    return addresses


def _is_seen(flags: Any) -> bool:
    if not isinstance(flags, list):
        return False
    for flag in flags:
        if not isinstance(flag, dict):
            continue
        if flag.get("iana") == "seen" or str(flag.get("raw", "")).lower() == "\\seen":
            return True
    return False


def _envelope_summary(envelope: Any) -> Optional[dict[str, Any]]:
    if not isinstance(envelope, dict):
        return None
    return {
        "from": _addresses(envelope.get("from")),
        "subject": _clean_text(envelope.get("subject"), 500),
        "date": _clean_text(envelope.get("date"), 64),
        "unread": not _is_seen(envelope.get("flags")),
        "has_attachment": envelope.get("has-attachment") is True,
    }


def _request_args(args: dict[str, Any]) -> Optional[Tuple[str, str, int]]:
    mailbox = args.get("mailbox", "INBOX")
    query = args.get("query", "")
    limit = args.get("limit", 10)
    if not isinstance(mailbox, str) or not mailbox.strip() or len(mailbox) > 128:
        return None
    if not isinstance(query, str) or len(query) > 500 or any(ord(char) < 32 for char in query):
        return None
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_LIMIT:
        return None
    return mailbox.strip(), query.strip(), limit


def gmail_list_emails(args: dict[str, Any], **kwargs: Any) -> str:
    """List or search envelope summaries using only the local Himalaya account."""
    if not isinstance(args, dict):
        return _error("Invalid Gmail request.")
    request = _request_args(args)
    if request is None:
        return _error("Use a mailbox name, a search query up to 500 characters, and a limit from 1 to 20.")
    mailbox, query, limit = request

    command = [
        HIMALAYA_BIN,
        "--config",
        str(HIMALAYA_CONFIG),
        "--account",
        HIMALAYA_ACCOUNT,
        "--json",
        "envelope",
        "search" if query else "list",
        "--mailbox",
        mailbox,
        "--page-size",
        str(limit),
    ]
    if query:
        command.append(query)

    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=COMMAND_TIMEOUT_SECONDS,
        )
    except FileNotFoundError:
        return _error("Himalaya is not installed on this Mac.")
    except subprocess.TimeoutExpired:
        return _error("Gmail did not respond in time. Try again shortly.")
    except OSError:
        return _error("Gmail could not be accessed on this Mac.")

    # Himalaya can encode failures as JSON while still returning status 0.
    if result.returncode != 0:
        return _error("Gmail could not be accessed. Verify Himalaya and Keychain access on this Mac.")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return _error("Gmail returned an unexpected response.")
    if not isinstance(payload, dict) or payload.get("error"):
        return _error("Gmail could not be accessed. Verify Himalaya and Keychain access on this Mac.")

    envelopes = payload.get("envelopes")
    if not isinstance(envelopes, list):
        return _error("Gmail returned an unexpected response.")
    messages = [summary for envelope in envelopes[:limit]
                if (summary := _envelope_summary(envelope)) is not None]
    return json.dumps(
        {
            "ok": True,
            "mailbox": mailbox,
            "count": len(messages),
            "messages": messages,
        },
        ensure_ascii=False,
    )
