"""Tests for the read-only Himalaya-backed Gmail Hermes plugin."""

from __future__ import annotations

import importlib
import json
from pathlib import Path
import subprocess
import sys

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
PLUGIN_ROOT = REPO_ROOT / "hermes-plugin"
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

tools = importlib.import_module("jarvis_gmail.tools")


def successful_envelopes(*, subject="Quarterly report", flags=None):
    return json.dumps({
        "envelopes": [{
            "id": "42",
            "from": [{"name": "Finance", "email": "finance@example.com"}],
            "subject": subject,
            "date": "2026-09-08T10:30:00Z",
            "flags": flags or [],
            "has-attachment": True,
        }],
    })


def test_list_uses_himalaya_configured_account_and_returns_envelope_summaries(monkeypatch):
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, successful_envelopes(flags=[{"iana": "seen", "raw": "\\Seen"}]), "")

    monkeypatch.setattr(tools.subprocess, "run", run)

    response = json.loads(tools.gmail_list_emails({"limit": 1}))

    assert response == {
        "ok": True,
        "mailbox": "INBOX",
        "count": 1,
        "messages": [{
            "from": [{"name": "Finance", "email": "finance@example.com"}],
            "subject": "Quarterly report",
            "date": "2026-09-08T10:30:00Z",
            "unread": False,
            "has_attachment": True,
        }],
    }
    command, kwargs = calls[0]
    assert command[:8] == [
        tools.HIMALAYA_BIN, "--config", str(tools.HIMALAYA_CONFIG), "--account",
        "gmail", "--json", "envelope", "list",
    ]
    assert kwargs["check"] is False and kwargs["capture_output"] is True
    assert kwargs["timeout"] == tools.COMMAND_TIMEOUT_SECONDS
    assert "shell" not in kwargs


def test_search_passes_query_as_one_argument_without_a_shell(monkeypatch):
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, successful_envelopes(), "")

    monkeypatch.setattr(tools.subprocess, "run", run)
    query = "subject report; rm -rf /"

    response = json.loads(tools.gmail_list_emails({"query": query, "mailbox": "Archive", "limit": 2}))

    assert response["ok"] is True
    command, kwargs = calls[0]
    assert command[7] == "search"
    assert command[-1] == query
    assert command[9] == "Archive"
    assert kwargs.get("shell") is None


@pytest.mark.parametrize("args", [
    {"limit": 0},
    {"limit": 21},
    {"limit": True},
    {"mailbox": ""},
    {"query": "subject report\n--config /tmp/other"},
])
def test_invalid_requests_do_not_start_himalaya(monkeypatch, args):
    monkeypatch.setattr(tools.subprocess, "run", lambda *a, **k: pytest.fail("CLI must not run"))

    response = json.loads(tools.gmail_list_emails(args))

    assert response["ok"] is False


def test_cli_errors_do_not_leak_keychain_or_secret_output(monkeypatch):
    secret = "TOP-SECRET-KEYCHAIN-VALUE"
    result = subprocess.CompletedProcess([], 0, json.dumps({"error": f"Secret command error: {secret}"}), secret)
    monkeypatch.setattr(tools.subprocess, "run", lambda *a, **k: result)

    rendered = tools.gmail_list_emails({})

    assert "Verify Himalaya and Keychain access" in rendered
    assert secret not in rendered


def test_plugin_is_explicitly_read_only():
    manifest = (PLUGIN_ROOT / "jarvis_gmail" / "plugin.yaml").read_text(encoding="utf-8")
    schema = importlib.import_module("jarvis_gmail.schemas").GMAIL_LIST_EMAILS

    assert manifest.splitlines()[0] == "name: jarvis_gmail"
    assert "send" not in manifest.lower()
    assert "READ-ONLY" in schema["description"]
