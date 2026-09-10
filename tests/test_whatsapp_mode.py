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
    # Keep the real one reachable: the restart path has its own tests below,
    # and everything else must never touch the real gateway.
    module._real_restart_gateway = module.restart_gateway
    module.restart_gateway = lambda: True
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


# --------------------------------------------------------------- gateway restart

def test_restart_goes_through_launchd_so_the_agent_does_not_stall(mode, monkeypatch, tmp_path):
    """Turning the stand-in on must not ask the gateway to kill itself.

    The switch normally runs as a Hermes tool call, so it is a child of the
    gateway. `hermes gateway restart` stopped the service and killed this
    process with it; launchd's KeepAlive brought the gateway back about a
    minute later, and for that minute JARVIS timed out. launchd is asked to do
    the whole restart instead, so it completes even when the caller dies.
    """
    plist = tmp_path / "ai.hermes.gateway.plist"
    plist.write_text("<plist/>")
    monkeypatch.setattr(mode, "GATEWAY_PLIST", plist)
    monkeypatch.setattr(mode.os, "getuid", lambda: 501)
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        return type("Done", (), {"returncode": 0})()

    monkeypatch.setattr(mode.subprocess, "run", fake_run)
    assert mode._real_restart_gateway() is True
    kicks = [c for c in calls if c and c[0] == "launchctl"]
    assert kicks[0] == ["launchctl", "kickstart", "-k", "gui/501/ai.hermes.gateway"]
    # The CLI path is the thing this test exists to rule out.
    assert not any("gateway" in argv and "restart" in argv for argv in calls[1:])


def port_probe(mode, monkeypatch, pid_for_kick):
    """Fake shell where `lsof -t` really answers with pids.

    Deliberately not a boolean stub of `api_listening`: the point of the fix is
    that the *old* listener still holding the port must not read as a finished
    restart, and only real pid output exercises that.
    """
    calls = {"kicks": 0, "argv": []}

    def fake_run(argv, **kwargs):
        calls["argv"].append(list(argv))
        if argv and argv[0] == "lsof":
            pids = pid_for_kick(calls["kicks"])
            return type("Done", (), {"returncode": 0, "stdout": pids})()
        if argv and argv[0] == "launchctl":
            calls["kicks"] += 1
        return type("Done", (), {"returncode": 0, "stdout": ""})()

    monkeypatch.setattr(mode.subprocess, "run", fake_run)
    monkeypatch.setattr(mode, "API_WAIT_SECONDS", 0.05)
    monkeypatch.setattr(mode.time, "sleep", lambda _s: None)
    return calls


def test_the_old_listener_still_holding_the_port_is_not_a_finished_restart(
        mode, monkeypatch, tmp_path):
    """The exact race the fix exists for.

    The replacement reaches for the port while the previous listener still has
    it. A plain "is something bound?" would call that a success and walk away,
    leaving a gateway that fails to bind and runs on without its API — the
    stand-in answers, the app says Hermes is unreachable.
    """
    plist = tmp_path / "ai.hermes.gateway.plist"
    plist.write_text("<plist/>")
    monkeypatch.setattr(mode, "GATEWAY_PLIST", plist)
    monkeypatch.setattr(mode.os, "getuid", lambda: 501)
    monkeypatch.setattr(mode, "RESTART_STAMP", tmp_path / "restart.stamp")
    # The old pid keeps the port until a second kickstart has been asked for.
    calls = port_probe(mode, monkeypatch, lambda k: "222\n" if k >= 2 else "111\n")

    assert mode._real_restart_gateway() is True
    kicks = [c for c in calls["argv"] if c and c[0] == "launchctl"]
    assert kicks == [["launchctl", "kickstart", "-k", "gui/501/ai.hermes.gateway"]] * 2


def test_a_port_that_never_changes_hands_is_a_failed_restart(mode, monkeypatch, tmp_path):
    """Two attempts and the same old listener: the caller must hear failure."""
    plist = tmp_path / "ai.hermes.gateway.plist"
    plist.write_text("<plist/>")
    monkeypatch.setattr(mode, "GATEWAY_PLIST", plist)
    monkeypatch.setattr(mode.os, "getuid", lambda: 501)
    monkeypatch.setattr(mode, "RESTART_STAMP", tmp_path / "restart.stamp")
    port_probe(mode, monkeypatch, lambda _k: "111\n")

    assert mode._real_restart_gateway() is False


def test_an_unanswerable_probe_does_not_force_a_second_restart(mode, monkeypatch, tmp_path):
    """No lsof, no judgement: never turn "cannot tell" into another restart."""
    plist = tmp_path / "ai.hermes.gateway.plist"
    plist.write_text("<plist/>")
    monkeypatch.setattr(mode, "GATEWAY_PLIST", plist)
    monkeypatch.setattr(mode.os, "getuid", lambda: 501)
    monkeypatch.setattr(mode, "RESTART_STAMP", tmp_path / "restart.stamp")
    calls = {"argv": []}

    def fake_run(argv, **kwargs):
        calls["argv"].append(list(argv))
        if argv and argv[0] == "lsof":
            raise OSError("lsof fehlt")
        return type("Done", (), {"returncode": 0, "stdout": ""})()

    monkeypatch.setattr(mode.subprocess, "run", fake_run)
    monkeypatch.setattr(mode, "API_WAIT_SECONDS", 0.05)
    monkeypatch.setattr(mode.time, "sleep", lambda _s: None)

    assert mode._real_restart_gateway() is True
    kicks = [c for c in calls["argv"] if c and c[0] == "launchctl"]
    assert len(kicks) == 1


def test_restart_falls_back_to_the_cli_when_no_service_is_installed(mode, monkeypatch, tmp_path):
    """A gateway nobody installed as a service is still a gateway to restart."""
    monkeypatch.setattr(mode, "GATEWAY_PLIST", tmp_path / "absent.plist")
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        return type("Done", (), {"returncode": 0})()

    monkeypatch.setattr(mode.subprocess, "run", fake_run)
    assert mode._real_restart_gateway() is True
    cli = [c for c in calls if c and c[0] != "lsof"]
    assert cli[0][1:] == ["gateway", "restart"]


def test_a_refused_kickstart_still_tries_the_cli(mode, monkeypatch, tmp_path):
    """A renamed or unloaded label must not be reported as a failed switch."""
    plist = tmp_path / "ai.hermes.gateway.plist"
    plist.write_text("<plist/>")
    monkeypatch.setattr(mode, "GATEWAY_PLIST", plist)
    monkeypatch.setattr(mode.os, "getuid", lambda: 501)
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        return type("Done", (), {"returncode": 0 if argv[0] != "launchctl" else 3})()

    monkeypatch.setattr(mode.subprocess, "run", fake_run)
    assert mode._real_restart_gateway() is True
    real = [c for c in calls if c and c[0] != "lsof"]
    assert real[0][0] == "launchctl"
    assert real[1][1:] == ["gateway", "restart"]
