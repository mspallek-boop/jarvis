"""The gateway half of an in-place WhatsApp switch: .env keys into the running process."""
import importlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "hermes-plugin"))

MANAGED = ("WHATSAPP_MODE", "WHATSAPP_ALLOWED_USERS",
           "WHATSAPP_FORWARD_OWNER_MESSAGES", "WHATSAPP_DEBUG")


@pytest.fixture
def plugin(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_WA_RELOAD_DIR", str(tmp_path))
    env = tmp_path / ".env"
    monkeypatch.setenv("JARVIS_WA_ENV", str(env))
    # Registered with monkeypatch so the real process environment is restored.
    monkeypatch.setenv("WHATSAPP_MODE", "self-chat")
    for key in MANAGED[1:]:
        monkeypatch.delenv(key, raising=False)
    module = importlib.import_module("jarvis_whatsapp_mode_reload")
    module._env = env
    return module


def test_only_the_managed_keys_are_taken_and_removed_ones_go(plugin):
    plugin._env.write_text("SOME_SECRET=nicht-anfassen\nWHATSAPP_MODE=bot\n"
                           "WHATSAPP_ALLOWED_USERS='491500000001'\n")
    environ = {"WHATSAPP_DEBUG": "1", "OTHER": "bleibt"}
    plugin.apply(plugin.read_managed(plugin._env), environ)
    assert environ == {"WHATSAPP_MODE": "bot", "WHATSAPP_ALLOWED_USERS": "491500000001",
                       "OTHER": "bleibt"}


def test_a_request_is_answered_with_its_id_and_the_new_mode(plugin):
    import os
    plugin._env.write_text("WHATSAPP_MODE=bot\nWHATSAPP_DEBUG=1\n")
    ack = plugin.handle_request(json.dumps({"id": "abc123"}))
    written = json.loads(plugin.ack_path().read_text())
    assert ack == written
    assert written["id"] == "abc123" and written["mode"] == "bot"
    assert "WHATSAPP_ALLOWED_USERS" not in written      # no numbers in the ack
    assert os.environ["WHATSAPP_MODE"] == "bot" and os.environ["WHATSAPP_DEBUG"] == "1"
    assert oct(plugin.ack_path().stat().st_mode & 0o777) == "0o600"


@pytest.mark.parametrize("raw", ["", "kein json", "{}", '["id"]'])
def test_a_malformed_request_changes_nothing(plugin, raw):
    import os
    plugin._env.write_text("WHATSAPP_MODE=bot\n")
    assert plugin.handle_request(raw) is None
    assert not plugin.ack_path().exists()
    assert os.environ["WHATSAPP_MODE"] == "self-chat"


def test_nothing_starts_outside_the_gateway(plugin, monkeypatch):
    monkeypatch.setattr(plugin, "_started", False)
    monkeypatch.setattr(plugin.sys, "argv", ["hermes", "-z", "hallo"])
    plugin.register(None)
    assert plugin._started is False
    assert plugin.in_gateway(["python", "-m", "hermes_cli.main", "gateway", "run"])
