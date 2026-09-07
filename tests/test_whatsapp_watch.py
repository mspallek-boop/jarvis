"""The WhatsApp reply watcher: does it nudge for the right person, once?"""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(tmp_path, monkeypatch):
    """Import the script fresh with every path pointed into a tmp dir."""
    log = tmp_path / "bridge.log"
    log.write_text("")
    session = tmp_path / "session"
    session.mkdir()
    monkeypatch.setenv("JARVIS_WA_LOG", str(log))
    monkeypatch.setenv("JARVIS_WA_SESSION", str(session))
    monkeypatch.setenv("JARVIS_WA_STATE", str(tmp_path / "state.json"))
    spec = importlib.util.spec_from_file_location(
        "wa_watch", ROOT / "scripts" / "jarvis-whatsapp-watch.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["wa_watch"] = module
    spec.loader.exec_module(module)
    return module, log, session


def run(module, *argv):
    sent = []
    module.notify = lambda name, speak: sent.append(name)
    old = sys.argv
    sys.argv = ["jarvis-whatsapp-watch.py", *argv]
    try:
        module.main()
    finally:
        sys.argv = old
    return sent


def run_status(module, *argv):
    old = sys.argv
    sys.argv = ["jarvis-whatsapp-watch.py", *argv]
    try:
        return module.main()
    finally:
        sys.argv = old


def inbound(log, chat_id, reason="self_chat_mode_rejects_non_self"):
    with log.open("a") as handle:
        handle.write(json.dumps({"event": "ignored", "reason": reason,
                                 "chatId": chat_id, "senderId": chat_id}) + "\n")


def test_reply_from_the_watched_chat_notifies_once(tmp_path, monkeypatch):
    module, log, _ = load(tmp_path, monkeypatch)
    run(module, "watch", "4915112345678@s.whatsapp.net", "--name", "Rici")
    inbound(log, "4915112345678@s.whatsapp.net")
    assert run(module, "poll", "--quiet") == ["Rici"]
    # The watch is spent: a second message from the same chat is just a message.
    inbound(log, "4915112345678@s.whatsapp.net")
    assert run(module, "poll", "--quiet") == []


def test_a_lid_reply_matches_the_phone_number_it_was_sent_to(tmp_path, monkeypatch):
    """WhatsApp reports inbound chats as a LID; sends address a phone JID.

    Without walking the session's mapping files the reply never matches, and
    the watcher looks broken while working perfectly.
    """
    module, log, session = load(tmp_path, monkeypatch)
    (session / "lid-mapping-4915112345678.json").write_text('"133285736910954"')
    (session / "lid-mapping-133285736910954_reverse.json").write_text('"4915112345678"')
    run(module, "watch", "4915112345678@s.whatsapp.net", "--name", "Rici")
    inbound(log, "133285736910954@lid")
    assert run(module, "poll", "--quiet") == ["Rici"]


def test_somebody_else_writing_does_not_fire_the_watch(tmp_path, monkeypatch):
    module, log, _ = load(tmp_path, monkeypatch)
    run(module, "watch", "4915112345678", "--name", "Rici")
    inbound(log, "999999999999@lid")
    assert run(module, "poll", "--quiet") == []


def test_messages_from_before_the_watch_are_not_replayed(tmp_path, monkeypatch):
    """Registering a watch must not fire on the backlog already in the log."""
    module, log, _ = load(tmp_path, monkeypatch)
    for _ in range(3):
        inbound(log, "4915112345678@s.whatsapp.net")
    run(module, "watch", "4915112345678", "--name", "Rici")
    assert run(module, "poll", "--quiet") == []


def test_a_restarted_bridge_truncating_its_log_is_survivable(tmp_path, monkeypatch):
    module, log, _ = load(tmp_path, monkeypatch)
    inbound(log, "999999999999@lid")
    inbound(log, "888888888888@lid")
    run(module, "watch", "4915112345678", "--name", "Rici")
    log.write_text("")                       # bridge restart truncates the log
    inbound(log, "4915112345678@s.whatsapp.net", reason="allowlist_mismatch")
    assert run(module, "poll", "--quiet") == ["Rici"]


def test_an_expired_watch_does_not_interrupt_days_later(tmp_path, monkeypatch):
    module, log, _ = load(tmp_path, monkeypatch)
    run(module, "watch", "4915112345678", "--name", "Rici", "--ttl", "48")
    state = json.loads((tmp_path / "state.json").read_text())
    state["watches"]["4915112345678"]["since"] -= 49 * 3600
    (tmp_path / "state.json").write_text(json.dumps(state))
    inbound(log, "4915112345678@s.whatsapp.net")
    assert run(module, "poll", "--quiet") == []


def test_noise_in_the_log_is_ignored(tmp_path, monkeypatch):
    module, log, _ = load(tmp_path, monkeypatch)
    run(module, "watch", "4915112345678", "--name", "Rici")
    with log.open("a") as handle:
        handle.write("⚠️  Connection closed (reason: 408). Reconnecting in 3s...\n")
        handle.write("{not json\n")
        handle.write(json.dumps({"event": "ignored", "reason": "foreign_poll_update"}) + "\n")
    assert run(module, "poll", "--quiet") == []


@pytest.mark.parametrize("bad", ["nonsense", "12", "+" + "9" * 40])
def test_a_chat_id_that_is_not_a_number_is_refused(tmp_path, monkeypatch, bad):
    module, _, _ = load(tmp_path, monkeypatch)
    assert run_status(module, "watch", bad) == 2


def test_the_state_file_stays_private(tmp_path, monkeypatch):
    """It holds contact numbers, so it must not be world-readable."""
    module, _, _ = load(tmp_path, monkeypatch)
    run(module, "watch", "4915112345678", "--name", "Rici")
    assert (tmp_path / "state.json").stat().st_mode & 0o077 == 0


def test_no_message_content_is_ever_stored(tmp_path, monkeypatch):
    module, log, _ = load(tmp_path, monkeypatch)
    run(module, "watch", "4915112345678", "--name", "Rici")
    with log.open("a") as handle:
        handle.write(json.dumps({"event": "ignored", "reason": "self_chat_mode_rejects_non_self",
                                 "chatId": "4915112345678@s.whatsapp.net",
                                 "senderId": "4915112345678@s.whatsapp.net",
                                 "text": "streng geheimer Inhalt"}) + "\n")
    run(module, "poll", "--quiet")
    assert "geheim" not in (tmp_path / "state.json").read_text()
