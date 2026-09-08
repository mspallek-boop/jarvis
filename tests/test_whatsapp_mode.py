"""The WhatsApp receive switch: does it flip cleanly, and flip back?"""
import importlib.util
import json
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

ENV_BEFORE = """SOME_OTHER_SECRET=nicht-anfassen
# WHATSAPP_ALLOWED_USERS=auskommentiert
WHATSAPP_MODE=self-chat
WHATSAPP_ALLOWED_USERS=491500000001,111200000000002
WHATSAPP_ENABLED=true
LAST_KEY=auch-nicht
"""


@pytest.fixture
def mode(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text(ENV_BEFORE)
    env.chmod(0o600)
    monkeypatch.setenv("JARVIS_WA_ENV", str(env))
    monkeypatch.setenv("JARVIS_WA_MODE_STATE", str(tmp_path / "mode.json"))
    spec = importlib.util.spec_from_file_location(
        "wa_mode", ROOT / "scripts" / "jarvis-whatsapp-mode.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["wa_mode"] = module
    spec.loader.exec_module(module)
    module.restart_gateway = lambda: True     # never touch the real gateway
    module._env_path = env
    return module


def run(module, *argv):
    old = sys.argv
    sys.argv = ["jarvis-whatsapp-mode.py", *argv]
    try:
        return module.main()
    finally:
        sys.argv = old


def keys(module):
    return module.read_env()


def test_default_is_off(mode):
    assert keys(mode)["WHATSAPP_MODE"] == "self-chat"


def test_on_without_a_contact_is_refused(mode):
    assert run(mode, "on") == 2
    assert keys(mode)["WHATSAPP_MODE"] == "self-chat"


def test_on_sets_all_three_keys_that_have_to_move_together(mode):
    """Bot mode alone kills the owner's own chat and blinds the reply watcher."""
    assert run(mode, "on", "--contact", "+49 170 1234567") == 0
    values = keys(mode)
    assert values["WHATSAPP_MODE"] == "bot"
    assert "491701234567" in values["WHATSAPP_ALLOWED_USERS"]
    assert values["WHATSAPP_FORWARD_OWNER_MESSAGES"] == "true"
    assert values["WHATSAPP_DEBUG"] == "true"


def test_the_existing_allowlist_is_kept(mode):
    run(mode, "on", "--contact", "491701234567")
    allowed = keys(mode)["WHATSAPP_ALLOWED_USERS"].split(",")
    assert "491500000001" in allowed and "111200000000002" in allowed


def test_a_wildcard_can_never_be_smuggled_in(mode):
    """`*` would make JARVIS answer strangers — argparse rejects it outright."""
    with pytest.raises(SystemExit):
        run(mode, "on", "--contact", "*")
    assert "*" not in keys(mode).get("WHATSAPP_ALLOWED_USERS", "")
    assert keys(mode)["WHATSAPP_MODE"] == "self-chat"


def test_off_restores_the_file_exactly(mode):
    run(mode, "on", "--contact", "491701234567", "--for", "2h")
    run(mode, "off")
    assert mode._env_path.read_text() == ENV_BEFORE


def test_unrelated_secrets_and_comments_survive(mode):
    run(mode, "on", "--contact", "491701234567")
    text = mode._env_path.read_text()
    assert "SOME_OTHER_SECRET=nicht-anfassen" in text
    assert "LAST_KEY=auch-nicht" in text
    assert "# WHATSAPP_ALLOWED_USERS=auskommentiert" in text


def test_the_env_file_stays_private(mode):
    run(mode, "on", "--contact", "491701234567")
    assert mode._env_path.stat().st_mode & 0o077 == 0


def test_a_second_on_does_not_destroy_the_saved_original(mode):
    run(mode, "on", "--contact", "491701234567", "--for", "1h")
    run(mode, "on", "--contact", "491709999999", "--for", "1h")
    run(mode, "off")
    assert mode._env_path.read_text() == ENV_BEFORE


def test_enforce_leaves_a_live_timer_alone(mode):
    run(mode, "on", "--contact", "491701234567", "--for", "2h")
    run(mode, "enforce")
    assert keys(mode)["WHATSAPP_MODE"] == "bot"


def test_enforce_switches_off_once_the_time_is_up(mode):
    run(mode, "on", "--contact", "491701234567", "--for", "2h")
    state = json.loads(Path(mode.STATE_PATH).read_text())
    state["until"] = time.time() - 1
    Path(mode.STATE_PATH).write_text(json.dumps(state))
    run(mode, "enforce")
    assert mode._env_path.read_text() == ENV_BEFORE


def test_without_a_duration_it_stays_on_until_told_otherwise(mode):
    run(mode, "on", "--contact", "491701234567")
    run(mode, "enforce")
    assert keys(mode)["WHATSAPP_MODE"] == "bot"


def test_morris_receive_window_is_owned_until_his_reply(mode):
    contact = "4915129583256@s.whatsapp.net"
    run(mode, "on", "--contact", contact, "--for", "48h", "--until-reply")
    state = json.loads(Path(mode.STATE_PATH).read_text())
    assert state["until_reply_contact"] == "4915129583256"
    assert keys(mode)["WHATSAPP_MODE"] == "bot"
    run(mode, "off", "--until-reply")
    assert mode._env_path.read_text() == ENV_BEFORE


def test_reply_off_cannot_disable_a_manual_receive_session(mode):
    mode._env_path.write_text(ENV_BEFORE.replace("WHATSAPP_MODE=self-chat", "WHATSAPP_MODE=bot"))
    run(mode, "on", "--contact", "4915129583256", "--for", "48h", "--until-reply")
    values = keys(mode)
    assert values["WHATSAPP_MODE"] == "bot"
    assert "4915129583256" in values["WHATSAPP_ALLOWED_USERS"]
    run(mode, "off", "--until-reply")
    values = keys(mode)
    assert values["WHATSAPP_MODE"] == "bot"
    assert "4915129583256" not in values["WHATSAPP_ALLOWED_USERS"]
    assert "491500000001" in values["WHATSAPP_ALLOWED_USERS"]


def test_until_reply_is_reserved_for_the_fixed_morris_contact(mode):
    assert run(mode, "on", "--contact", "491701234567", "--for", "48h", "--until-reply") == 2
    assert keys(mode)["WHATSAPP_MODE"] == "self-chat"


def test_a_lost_state_file_falls_back_to_off_not_to_stuck_on(mode):
    run(mode, "on", "--contact", "491701234567")
    Path(mode.STATE_PATH).unlink()
    run(mode, "off")
    assert keys(mode)["WHATSAPP_MODE"] == "self-chat"


@pytest.mark.parametrize("bad", ["nonsense", "12", "9" * 30])
def test_junk_contacts_are_refused(mode, bad):
    with pytest.raises(SystemExit):
        run(mode, "on", "--contact", bad)


@pytest.mark.parametrize("bad", ["", "2 Wochen", "0h", "999d"])
def test_junk_durations_are_refused(mode, bad):
    with pytest.raises(SystemExit):
        run(mode, "on", "--contact", "491701234567", "--for", bad)


def test_a_backup_of_the_env_is_written_before_any_change(mode):
    run(mode, "on", "--contact", "491701234567")
    backups = list(Path(mode._env_path).parent.glob("*.bak.wamode.*"))
    assert backups and backups[0].read_text() == ENV_BEFORE
