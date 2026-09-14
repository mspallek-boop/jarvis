"""Chat stand-in: does it ask both questions, pace reports, and end itself?"""
import importlib.util
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
KEY = "4917648090349"


def load(tmp_path, monkeypatch):
    """Import the script fresh with its state pointed into a tmp dir."""
    monkeypatch.setenv("JARVIS_STANDIN_STATE", str(tmp_path / "standin.json"))
    monkeypatch.setenv("JARVIS_WA_MODE_STATE", str(tmp_path / "mode.json"))
    monkeypatch.setenv("JARVIS_WA_CREDS", str(tmp_path / "creds.json"))
    # Never the real one: a test must not read the user's live WhatsApp state.
    monkeypatch.setenv("JARVIS_HERMES_ENV", str(tmp_path / "env"))
    monkeypatch.setenv("JARVIS_OWNER_NAME", "Marlon")
    monkeypatch.setenv("JARVIS_RESTART_STAMP", str(tmp_path / "restart.stamp"))
    monkeypatch.setenv("JARVIS_WA_BRIDGE_LOG", str(tmp_path / "bridge.log"))
    spec = importlib.util.spec_from_file_location(
        "chat_standin", ROOT / "scripts" / "jarvis-chat-standin.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["chat_standin"] = module
    spec.loader.exec_module(module)
    # Nothing in a test may reach the bridge, WhatsApp, the speaker or the
    # mode switch.
    sent, told, shell = [], [], []
    module.deliver = (lambda title, text, speak, spoken="":
                      sent.append((title, text, spoken)))
    module.tell_contact = lambda key, text: told.append((key, text)) is None
    # Stubbed at the shell rather than at our own helpers, so the helpers stay
    # observable: a test about "does it switch receiving off" has to be able to
    # see that it did.
    monkeypatch.setattr(module.subprocess, "run",
                        lambda argv, **k: shell.append(list(argv)) or
                        type("R", (), {"returncode": 0, "stderr": ""})())
    module.shell = shell
    return module, sent, told


def run(module, *argv):
    return module.main(list(argv))


def begin(module, hours=2.0, name="Marie", key=KEY, announced=False):
    """Write the record directly: `start` flips real WhatsApp receiving."""
    now = time.time()
    state = module.load()
    state["standins"][key] = {"name": name, "started": now, "until": now + hours * 3600,
                              "announced": announced, "pending": [], "inbound": [],
                              "last_report": now, "reported": 0}
    module.save(state)
    return key, now


# ------------------------------------------------------------ both consents

def test_start_refuses_without_an_announcement_decision(tmp_path, monkeypatch):
    """No default: that is how "did you ask?" becomes "I assumed"."""
    module, _, _ = load(tmp_path, monkeypatch)
    with pytest.raises(SystemExit):
        run(module, "start", KEY, "--for", "1h")


def test_a_standin_needs_one_real_number(tmp_path, monkeypatch):
    """No wildcard stand-in: an open bot would answer strangers."""
    module, _, _ = load(tmp_path, monkeypatch)
    for contact in ["*", "", "alle", "+49 176 x"]:
        assert run(module, "start", contact, "--for", "1h", "--no-announce") == 2
    assert module.load()["standins"] == {}


BOT_UP = ("🌉 WhatsApp bridge listening on port 3000 (mode: bot)",
          "🔒 Allowed users: 4915129577496, " + KEY,
          "✅ WhatsApp connected!")


def bridge_says(module, *lines):
    with module.BRIDGE_LOG.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def test_announcing_tells_the_contact_once_receiving_is_up(tmp_path, monkeypatch):
    """The announcement waits for a bridge that can hear the contact.

    Telling someone an assistant answers while their messages are still dropped
    is the promise the 2026-09-14 test stand-in broke.
    """
    module, sent, told = load(tmp_path, monkeypatch)
    assert run(module, "start", KEY, "--name", "Marie", "--for", "2h", "--announce") == 0
    assert told == [] and module.load()["standins"][KEY]["announced"] is False
    bridge_says(module, *BOT_UP)
    run(module, "poll")
    assert len(told) == 1
    text = told[0][1]
    assert "KI-Assistent" in text and "2 Stunden" in text and "Marlon" in text
    assert module.load()["standins"][KEY]["announced"] is True
    assert "läuft" in sent[-1][1]


def test_not_announcing_says_nothing_to_the_contact(tmp_path, monkeypatch):
    module, _, told = load(tmp_path, monkeypatch)
    assert run(module, "start", KEY, "--for", "1h", "--no-announce") == 0
    assert told == []
    assert module.load()["standins"][KEY]["announced"] is False


def test_a_failed_announcement_cancels_the_whole_standin(tmp_path, monkeypatch):
    """Promising transparency and not delivering it is worse than not offering."""
    module, sent, _ = load(tmp_path, monkeypatch)
    module.tell_contact = lambda key, text: False
    assert run(module, "start", KEY, "--for", "1h", "--announce") == 0
    bridge_says(module, *BOT_UP)
    run(module, "poll")
    assert module.load()["standins"] == {}
    assert "nicht gestartet" in sent[-1][1]


def test_an_announced_standin_says_goodbye_too(tmp_path, monkeypatch):
    module, _, told = load(tmp_path, monkeypatch)
    begin(module, announced=True)
    run(module, "stop", KEY)
    assert len(told) == 1 and "wieder selbst da" in told[0][1]


def test_a_silent_standin_stays_silent_at_the_end(tmp_path, monkeypatch):
    module, _, told = load(tmp_path, monkeypatch)
    begin(module, announced=False)
    run(module, "stop", KEY)
    assert told == []


# --------------------------------------------------------------- suggesting

def test_a_standin_is_suggested_once_then_left_alone(tmp_path, monkeypatch):
    module, _, _ = load(tmp_path, monkeypatch)
    assert run(module, "offer", KEY) == 0
    assert run(module, "offer", KEY) == 1      # nagging is how it gets ignored


def test_nothing_is_suggested_while_one_is_running(tmp_path, monkeypatch):
    module, _, _ = load(tmp_path, monkeypatch)
    begin(module)
    assert run(module, "offer", KEY) == 1


def test_the_suggestion_returns_after_the_cooldown(tmp_path, monkeypatch):
    module, _, _ = load(tmp_path, monkeypatch)
    run(module, "offer", KEY)
    state = module.load()
    state["offers"][KEY] = time.time() - module.OFFER_COOLDOWN_SECONDS - 1
    module.save(state)
    assert run(module, "offer", KEY) == 0


# ------------------------------------------------------------------- pacing

def test_a_quiet_chat_is_reported_almost_at_once(tmp_path, monkeypatch):
    module, _, _ = load(tmp_path, monkeypatch)
    key, now = begin(module)
    standin = module.load()["standins"][key]
    standin["last_report"] = now - 200          # one message, three minutes ago
    standin["inbound"] = [now - 200]
    standin["pending"] = [{"at": now, "gist": "fragt nach Samstag", "urgent": False}]
    assert module.report_interval(standin, now) == 120
    assert module.report_due(standin, now) is True


def test_a_lively_chat_is_batched(tmp_path, monkeypatch):
    module, _, _ = load(tmp_path, monkeypatch)
    key, now = begin(module)
    standin = module.load()["standins"][key]
    standin["inbound"] = [now - i * 60 for i in range(9)]
    standin["last_report"] = now - 300          # five minutes is not enough now
    standin["pending"] = [{"at": now, "gist": "schreibt viel", "urgent": False}]
    assert module.report_interval(standin, now) == 1200
    assert module.report_due(standin, now) is False


def test_urgent_jumps_the_queue(tmp_path, monkeypatch):
    module, _, _ = load(tmp_path, monkeypatch)
    key, now = begin(module)
    standin = module.load()["standins"][key]
    standin["inbound"] = [now - i * 30 for i in range(20)]   # as busy as it gets
    standin["last_report"] = now
    standin["pending"] = [{"at": now, "gist": "weiß nicht weiter", "urgent": True}]
    assert module.report_due(standin, now) is True


def test_nothing_pending_is_never_reported(tmp_path, monkeypatch):
    module, _, _ = load(tmp_path, monkeypatch)
    key, now = begin(module)
    standin = module.load()["standins"][key]
    standin["last_report"] = now - 10_000
    assert module.report_due(standin, now) is False


def test_note_without_a_standin_is_refused(tmp_path, monkeypatch):
    module, sent, _ = load(tmp_path, monkeypatch)
    assert run(module, "note", KEY, "--gist", "x") == 1
    assert sent == []


def test_a_burst_becomes_one_report_not_six(tmp_path, monkeypatch):
    """Six messages in a few seconds is one thing happening, not six."""
    module, sent, _ = load(tmp_path, monkeypatch)
    key, now = begin(module)
    for i in range(6):
        run(module, "note", key, "--gist", f"nachricht {i}")
    assert sent == []                       # all of it held back
    assert len(module.load()["standins"][key]["pending"]) == 6

    state = module.load()
    state["standins"][key]["last_report"] = now - 2000
    module.save(state)
    run(module, "poll")
    assert len(sent) == 1
    assert "nachricht 0" in sent[0][1] and "nachricht 5" in sent[0][1]
    assert module.load()["standins"][key]["pending"] == []


def test_a_report_never_becomes_a_wall_of_text(tmp_path, monkeypatch):
    module, _, _ = load(tmp_path, monkeypatch)
    key, now = begin(module)
    standin = module.load()["standins"][key]
    standin["pending"] = [{"at": now, "gist": f"zeile {i}", "urgent": False} for i in range(20)]
    text = module.summarise(standin)
    assert text.count("·") == module.MAX_GIST_LINES      # 8 lines, 8 separators
    assert "+12 weitere" in text


# ------------------------------------------------------------------- expiry

def test_poll_ends_a_standin_that_has_run_out(tmp_path, monkeypatch):
    module, sent, _ = load(tmp_path, monkeypatch)
    key, now = begin(module)
    state = module.load()
    state["standins"][key]["until"] = now - 1
    state["standins"][key]["pending"] = [{"at": now, "gist": "letztes", "urgent": False}]
    module.save(state)
    assert run(module, "poll") == 0
    assert module.load()["standins"] == {}
    assert "beendet" in sent[-1][1]


def test_poll_leaves_a_running_standin_alone(tmp_path, monkeypatch):
    module, sent, _ = load(tmp_path, monkeypatch)
    key, _ = begin(module)
    assert run(module, "poll") == 0
    assert key in module.load()["standins"]
    assert sent == []


# ------------------------------------------------------------------- limits

@pytest.mark.parametrize("text,hours", [("2h", 2.0), ("90m", 1.5), ("1,5h", 1.5)])
def test_durations_that_make_sense(tmp_path, monkeypatch, text, hours):
    module, _, _ = load(tmp_path, monkeypatch)
    assert module.parse_duration(text) == pytest.approx(hours)


@pytest.mark.parametrize("text", ["", "morgen", "0h", "-2h", "9h", "2 Tage", "24h"])
def test_durations_that_do_not(tmp_path, monkeypatch, text):
    module, _, _ = load(tmp_path, monkeypatch)
    with pytest.raises(ValueError):
        module.parse_duration(text)


def test_state_file_is_not_world_readable(tmp_path, monkeypatch):
    """Contact numbers and gists are personal data."""
    module, _, _ = load(tmp_path, monkeypatch)
    begin(module)
    assert oct((tmp_path / "standin.json").stat().st_mode)[-3:] == "600"


# ------------------------------------------------- the shared receiving window

def mode_window(module, seconds_left):
    """Pretend jarvis-whatsapp-mode.py holds a window this long."""
    import json
    module.MODE_STATE_PATH.write_text(json.dumps({"until": time.time() + seconds_left}))


def test_a_short_standin_never_shortens_a_long_one(tmp_path, monkeypatch):
    """One global mode timer: whoever needs it longest sets the window."""
    module, _, _ = load(tmp_path, monkeypatch)
    asked = []
    monkeypatch.setattr(module, "switch_receiving_on",
                        lambda contacts, hours: asked.append((sorted(contacts), hours)) is None or True)
    begin(module, hours=8.0, key="4917648090349", name="Marie")
    assert run(module, "start", "4915129050434", "--for", "5m", "--no-announce") == 0
    assert asked[-1][1] == pytest.approx(8.0, abs=0.01)   # not 0.083
    assert asked[-1][0] == ["4915129050434", "4917648090349"]


def test_poll_reopens_a_window_that_fell_short(tmp_path, monkeypatch):
    module, _, _ = load(tmp_path, monkeypatch)
    asked = []
    monkeypatch.setattr(module, "switch_receiving_on",
                        lambda contacts, hours: asked.append((sorted(contacts), hours)) is None or True)
    begin(module, hours=8.0)
    mode_window(module, 60)                 # about to expire under a long stand-in
    run(module, "poll")
    assert asked and asked[-1][1] == pytest.approx(8.0, abs=0.05)


def env_allowlist(module, contacts):
    module.ENV_PATH.write_text("WHATSAPP_ALLOWED_USERS=" + ",".join(contacts) + "\n")


def test_poll_leaves_a_sufficient_window_alone(tmp_path, monkeypatch):
    """Switching the mode restarts the gateway — not every minute."""
    module, _, _ = load(tmp_path, monkeypatch)
    asked = []
    monkeypatch.setattr(module, "switch_receiving_on",
                        lambda contacts, hours: asked.append((sorted(contacts), hours)) is None or True)
    key, _ = begin(module, hours=2.0)
    env_allowlist(module, [key])
    mode_window(module, 3 * 3600)
    run(module, "poll")
    assert asked == []


def test_no_standins_means_no_window_to_hold(tmp_path, monkeypatch):
    module, _, _ = load(tmp_path, monkeypatch)
    asked = []
    monkeypatch.setattr(module, "switch_receiving_on",
                        lambda contacts, hours: asked.append((sorted(contacts), hours)) is None or True)
    run(module, "poll")
    assert asked == []


def test_an_ended_standin_leaves_the_allowlist(tmp_path, monkeypatch):
    """The gap: a contact stayed allow-listed after their stand-in ended, and
    was answered automatically for hours with nothing behind it."""
    module, _, _ = load(tmp_path, monkeypatch)
    asked = []
    monkeypatch.setattr(module, "switch_receiving_on",
                        lambda contacts, hours: asked.append(sorted(contacts)) is None or True)
    monkeypatch.setattr(module, "allowlist", lambda: {"4917648090349", "4915129050434"})
    begin(module, hours=8.0, key="4917648090349", name="Marie")   # only Marie runs
    run(module, "poll")
    assert asked == [["4917648090349"]]      # the other one is dropped


def test_a_matching_allowlist_is_left_alone(tmp_path, monkeypatch):
    module, _, _ = load(tmp_path, monkeypatch)
    asked = []
    monkeypatch.setattr(module, "switch_receiving_on",
                        lambda contacts, hours: asked.append(sorted(contacts)) is None or True)
    monkeypatch.setattr(module, "allowlist", lambda: {"4917648090349"})
    begin(module, hours=2.0, key="4917648090349")
    mode_window(module, 3 * 3600)
    run(module, "poll")
    assert asked == []


def own_account(module, tmp_path):
    """The owner's own WhatsApp identities, as the bridge session records them."""
    import json
    module.WA_CREDS.write_text(json.dumps(
        {"me": {"id": "4915129577496:13@s.whatsapp.net", "lid": "111244551954649:13@lid"}}))
    return {"4915129577496", "111244551954649"}


def test_the_owner_is_never_dropped_from_the_allowlist(tmp_path, monkeypatch):
    """Setting the list to exactly the stand-ins would kill the user's own
    WhatsApp chat with JARVIS — which reads as JARVIS having gone deaf."""
    module, _, _ = load(tmp_path, monkeypatch)
    mine = own_account(module, tmp_path)
    asked = []
    monkeypatch.setattr(module.subprocess, "run",
                        lambda argv, **k: asked.extend(argv) or
                        type("R", (), {"returncode": 0, "stderr": ""})())
    module.switch_receiving_on(["4917648090349"], 2.0)
    passed = {asked[i + 1] for i, a in enumerate(asked) if a == "--contact"}
    assert passed == mine | {"4917648090349"}
    assert "--exclusive" in asked


def test_the_owner_alone_is_not_a_reason_to_reopen(tmp_path, monkeypatch):
    """The owner is always on the list, so it must not read as a mismatch."""
    module, _, _ = load(tmp_path, monkeypatch)
    mine = own_account(module, tmp_path)
    asked = []
    monkeypatch.setattr(module, "switch_receiving_on",
                        lambda contacts, hours: asked.append(sorted(contacts)) is None or True)
    monkeypatch.setattr(module, "allowlist", lambda: mine | {"4917648090349"})
    begin(module, hours=2.0, key="4917648090349")
    mode_window(module, 3 * 3600)
    run(module, "poll")
    assert asked == []


# --------------------------------------------------------- what happened so far

def test_notes_are_counted_and_kept_past_a_report(tmp_path, monkeypatch):
    """`pending` is emptied on every report, so it cannot answer "what has
    happened"; the interface needs something that survives the flush."""
    module, _, _ = load(tmp_path, monkeypatch)
    key, now = begin(module)
    for i in range(4):
        run(module, "note", key, "--gist", f"punkt {i}")
    state = module.load()
    state["standins"][key]["last_report"] = now - 2000
    module.save(state)
    run(module, "poll")                       # flushes pending

    standin = module.load()["standins"][key]
    assert standin["pending"] == []
    assert standin["exchanges"] == 4
    assert [h["gist"] for h in standin["history"]] == [f"punkt {i}" for i in range(4)]


def test_the_history_stays_a_state_file(tmp_path, monkeypatch):
    module, _, _ = load(tmp_path, monkeypatch)
    key, _ = begin(module)
    for i in range(module.MAX_HISTORY + 20):
        run(module, "note", key, "--gist", f"z{i}")
    standin = module.load()["standins"][key]
    assert len(standin["history"]) == module.MAX_HISTORY
    assert standin["history"][-1]["gist"] == f"z{module.MAX_HISTORY + 19}"
    assert standin["exchanges"] == module.MAX_HISTORY + 20   # counted, not kept


# ------------------------------------------------- the user takes over








def test_takeover_without_a_standin_is_refused(tmp_path, monkeypatch):
    module, sent, _ = load(tmp_path, monkeypatch)
    assert run(module, "takeover", "4917648090349") == 1
    assert sent == []


def test_the_user_writing_ends_the_standin_outright(tmp_path, monkeypatch):
    """Not a question and not a pause: there is no reading of "I am typing here
    myself" under which JARVIS should carry on."""
    module, sent, told = load(tmp_path, monkeypatch)
    key, _ = begin(module, announced=True)
    assert run(module, "takeover", key) == 0
    assert module.load()["standins"] == {}
    assert "du schreibst selbst" in sent[-1][1]
    assert told and "wieder selbst da" in told[-1][1]   # she is told too


def test_taking_over_a_chat_with_no_standin_is_refused(tmp_path, monkeypatch):
    module, sent, _ = load(tmp_path, monkeypatch)
    assert run(module, "takeover", "4917648090349") == 1
    assert sent == []


def test_the_last_takeover_switches_receiving_off(tmp_path, monkeypatch):
    module, _, _ = load(tmp_path, monkeypatch)
    key, _ = begin(module)
    module.ENV_PATH.write_text("WHATSAPP_MODE=bot\n")
    run(module, "takeover", key)
    assert [c[-1] for c in module.shell] == ["off"]


# ------------------------------------- reading the conversation from the log

def gateway_log(tmp_path, monkeypatch, module, lines):
    path = tmp_path / "gateway.log"
    path.write_text("\n".join(lines) + "\n")
    monkeypatch.setattr(module, "GATEWAY_LOG", path)
    return path


def inbound(stamp, chat, text):
    return (f"{stamp},001 INFO gateway.run: inbound message: platform=whatsapp "
            f"user=Marie chat={chat} msg='{text}' reply_to_id=None reply_to_text=''")


def test_the_conversation_is_read_from_the_gateway_log(tmp_path, monkeypatch):
    """A stand-in must report context even though JARVIS cannot call `note`.

    In a WhatsApp turn the agent has the WhatsApp toolset and no terminal, so
    the `note` path is unreachable and the app showed "noch nichts passiert"
    through a live conversation. The gateway's own log is the one place the
    message bodies exist.
    """
    module, _, _ = load(tmp_path, monkeypatch)
    key, started = begin(module)
    stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(started + 5))
    gateway_log(tmp_path, monkeypatch, module,
                [inbound(stamp, f"{key}@s.whatsapp.net", "Kommst du Samstag?")])

    state = module.load()
    assert module.scan_gateway_log(state, time.time()) is True
    standin = state["standins"][key]
    assert standin["exchanges"] == 1
    assert [item["gist"] for item in standin["pending"]] == ["Kommst du Samstag?"]


def test_a_lid_is_matched_to_the_number_the_standin_was_started_from(tmp_path, monkeypatch):
    """Inbound chats arrive as a LID; the stand-in holds a phone number."""
    module, _, _ = load(tmp_path, monkeypatch)
    session = tmp_path / "session"
    session.mkdir()
    (session / f"lid-mapping-{KEY}.json").write_text('"133285736910954@lid"')
    monkeypatch.setattr(module, "SESSION_DIR", session)
    key, started = begin(module)
    stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(started + 5))
    gateway_log(tmp_path, monkeypatch, module,
                [inbound(stamp, "133285736910954@lid", "Hallo?")])

    state = module.load()
    assert module.scan_gateway_log(state, time.time()) is True
    assert state["standins"][key]["exchanges"] == 1


def test_messages_from_before_the_standin_are_not_its_conversation(tmp_path, monkeypatch):
    """Reading the log from the top must not replay yesterday at the user."""
    module, _, _ = load(tmp_path, monkeypatch)
    key, started = begin(module)
    old = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(started - 3600))
    gateway_log(tmp_path, monkeypatch, module,
                [inbound(old, f"{key}@s.whatsapp.net", "von gestern")])

    state = module.load()
    module.scan_gateway_log(state, time.time())
    assert state["standins"][key].get("exchanges", 0) == 0


def test_a_second_scan_does_not_count_the_same_message_twice(tmp_path, monkeypatch):
    """The poll runs every minute; the log does not shrink between ticks."""
    module, _, _ = load(tmp_path, monkeypatch)
    key, started = begin(module)
    stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(started + 5))
    gateway_log(tmp_path, monkeypatch, module,
                [inbound(stamp, f"{key}@s.whatsapp.net", "Kommst du Samstag?")])

    state = module.load()
    module.scan_gateway_log(state, time.time())
    module.save(state)
    state = module.load()
    module.scan_gateway_log(state, time.time())
    assert state["standins"][key]["exchanges"] == 1


def test_a_chat_that_is_not_a_standin_is_ignored(tmp_path, monkeypatch):
    """Reading the whole log must not turn every chat into a report."""
    module, _, _ = load(tmp_path, monkeypatch)
    key, started = begin(module)
    stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(started + 5))
    gateway_log(tmp_path, monkeypatch, module,
                [inbound(stamp, "4900000000000@s.whatsapp.net", "fremder Chat")])

    state = module.load()
    module.scan_gateway_log(state, time.time())
    assert state["standins"][key].get("exchanges", 0) == 0


def test_a_deaf_gateway_is_kickstarted_once(tmp_path, monkeypatch):
    """A gateway running without its API port leaves the app without Hermes."""
    module, _, _ = load(tmp_path, monkeypatch)
    monkeypatch.setattr(module, "api_listening", lambda: False)
    monkeypatch.setattr(module, "gateway_service_running", lambda: True)
    module.shell.clear()
    module.ensure_api_up()
    assert module.shell == [["launchctl", "kickstart", "-k",
                             f"gui/{module.os.getuid()}/{module.GATEWAY_LABEL}"]]


def test_a_gateway_the_user_stopped_stays_stopped(tmp_path, monkeypatch):
    """Absent is not broken: only a running service that lost its port."""
    module, _, _ = load(tmp_path, monkeypatch)
    monkeypatch.setattr(module, "api_listening", lambda: False)
    monkeypatch.setattr(module, "gateway_service_running", lambda: False)
    module.shell.clear()
    module.ensure_api_up()
    assert module.shell == []


# ------------------------------------ what the log actually looks like

def real_line(user, chat, msg, stamp):
    """A line in the gateway's own format: it logs the body with %r."""
    return (f"{stamp},044 INFO gateway.run: inbound message: platform=whatsapp "
            f"user={user} chat={chat} msg={msg!r} reply_to_id=None reply_to_text=''")


def test_an_apostrophe_does_not_hide_a_message(tmp_path, monkeypatch):
    """`repr("Wie geht's?")` comes out double-quoted.

    Matching only `msg='` dropped every German message with an apostrophe —
    "geht's", "gibt's", "hab's" — silently and invisibly.
    """
    module, _, _ = load(tmp_path, monkeypatch)
    key, started = begin(module)
    stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(started + 5))
    gateway_log(tmp_path, monkeypatch, module,
                [real_line("Marie", f"{key}@s.whatsapp.net", "Wie geht's?", stamp)])

    state = module.load()
    module.scan_gateway_log(state, time.time())
    assert [i["gist"] for i in state["standins"][key]["pending"]] == ["Wie geht's?"]


def test_a_push_name_with_a_space_is_still_matched(tmp_path, monkeypatch):
    """WhatsApp push names contain spaces: "Marlon Spallek"."""
    module, _, _ = load(tmp_path, monkeypatch)
    key, started = begin(module)
    stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(started + 5))
    gateway_log(tmp_path, monkeypatch, module,
                [real_line("Anna Maria", f"{key}@s.whatsapp.net", "Hallo", stamp)])

    state = module.load()
    module.scan_gateway_log(state, time.time())
    assert state["standins"][key]["exchanges"] == 1


def test_the_users_own_message_is_not_the_contacts(tmp_path, monkeypatch):
    """In bot mode the owner's own messages are forwarded and logged too.

    They carry an `[owner reply]` prefix. Counting them would report the user's
    own words back to him and speak them aloud.
    """
    module, _, _ = load(tmp_path, monkeypatch)
    key, started = begin(module)
    stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(started + 5))
    gateway_log(tmp_path, monkeypatch, module,
                [real_line("Marlon Spallek", f"{key}@s.whatsapp.net",
                           "[owner reply] Ja passt", stamp)])

    state = module.load()
    module.scan_gateway_log(state, time.time())
    assert state["standins"][key].get("exchanges", 0) == 0


def test_a_half_written_last_line_is_not_lost(tmp_path, monkeypatch):
    """The gateway may be mid-write when the poll runs.

    Consuming the fragment and moving the offset past it loses the message for
    good; it must be left for the next tick instead.
    """
    module, _, _ = load(tmp_path, monkeypatch)
    key, started = begin(module)
    stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(started + 5))
    full = real_line("Marie", f"{key}@s.whatsapp.net", "Kommst du?", stamp)
    path = tmp_path / "gateway.log"
    path.write_text(full[:60])                       # torn off mid-line
    monkeypatch.setattr(module, "GATEWAY_LOG", path)

    state = module.load()
    module.scan_gateway_log(state, time.time())
    assert state["standins"][key].get("exchanges", 0) == 0

    path.write_text(full + "\n")                      # the writer finishes
    module.scan_gateway_log(state, time.time())
    assert [i["gist"] for i in state["standins"][key]["pending"]] == ["Kommst du?"]


def test_an_ambiguous_alias_is_dropped_not_guessed(tmp_path, monkeypatch):
    """Two stand-ins, one stale mapping, the same alias.

    Putting one contact's words into the other's report is worse than missing
    them, so an alias that resolves to two stand-ins attributes to neither.
    """
    module, _, _ = load(tmp_path, monkeypatch)
    other = "4911111111111"
    key, started = begin(module)
    begin(module, key=other, name="Andi")
    monkeypatch.setattr(module, "aliases", lambda _k: {"shared", "x"})
    stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(started + 5))
    gateway_log(tmp_path, monkeypatch, module,
                [real_line("Marie", "shared@lid", "wem gehoert das?", stamp)])

    state = module.load()
    module.scan_gateway_log(state, time.time())
    assert state["standins"][key].get("exchanges", 0) == 0
    assert state["standins"][other].get("exchanges", 0) == 0


def test_two_identical_replies_stay_two_events(tmp_path, monkeypatch):
    """"Ja" twice in a row is two messages, not one repeated."""
    module, _, _ = load(tmp_path, monkeypatch)
    key, started = begin(module)
    first = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(started + 5))
    second = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(started + 7))
    gateway_log(tmp_path, monkeypatch, module,
                [real_line("Marie", f"{key}@s.whatsapp.net", "Ja", first),
                 real_line("Marie", f"{key}@s.whatsapp.net", "Ja", second)])

    state = module.load()
    module.scan_gateway_log(state, time.time())
    assert state["standins"][key]["exchanges"] == 2


# ---------------------------------------------- what may be said out loud

def test_a_quoted_message_is_shown_but_not_spoken(tmp_path, monkeypatch):
    """The app is a screen he chose to look at; the speaker is a room.

    A line lifted from the log is the other person's words verbatim — it goes
    to the app, and the announcement is a count.
    """
    module, sent, _ = load(tmp_path, monkeypatch)
    key, now = begin(module)
    state = module.load()
    standin = state["standins"][key]
    standin["pending"] = [{"at": now, "gist": "Befund ist positiv", "src": "log"}]
    module.flush(state, key, standin, now, speak=True)

    title, shown, spoken = sent[-1]
    assert "Befund ist positiv" in shown          # visible in the app
    assert "Befund" not in spoken                 # never on a speaker
    assert "eine neue Nachricht" in spoken


def test_a_gist_jarvis_wrote_is_still_spoken(tmp_path, monkeypatch):
    """Its own summary is its own words: nothing to withhold."""
    module, sent, _ = load(tmp_path, monkeypatch)
    key, now = begin(module)
    state = module.load()
    standin = state["standins"][key]
    standin["pending"] = [{"at": now, "gist": "fragt nach Samstag"}]
    module.flush(state, key, standin, now, speak=True)

    _title, shown, spoken = sent[-1]
    assert "fragt nach Samstag" in shown and "fragt nach Samstag" in spoken


# --------------------------------------------- the gateway guard's limits

def test_the_guard_does_not_restart_twice_in_the_cooldown(tmp_path, monkeypatch):
    """The mode script and this poller must not kickstart on top of each other."""
    module, _, _ = load(tmp_path, monkeypatch)
    monkeypatch.setattr(module, "api_listening", lambda: False)
    monkeypatch.setattr(module, "gateway_service_running", lambda: True)
    module.shell.clear()
    module.ensure_api_up()
    module.ensure_api_up()
    assert len([c for c in module.shell if c[0] == "launchctl"]) == 1


def test_the_guard_gives_up_instead_of_looping(tmp_path, monkeypatch):
    """A permanently broken API must not interrupt a live chat every minute."""
    module, _, _ = load(tmp_path, monkeypatch)
    monkeypatch.setattr(module, "api_listening", lambda: False)
    monkeypatch.setattr(module, "gateway_service_running", lambda: True)
    monkeypatch.setattr(module, "RESTART_COOLDOWN_SECONDS", 0.0)
    module.shell.clear()
    for _ in range(10):
        module.ensure_api_up()
    kicks = [c for c in module.shell if c[0] == "launchctl"]
    assert len(kicks) == module.MAX_RESTART_ATTEMPTS


def test_a_healthy_port_forgets_the_attempt_history(tmp_path, monkeypatch):
    """Once it works again, the next outage gets its full budget."""
    module, _, _ = load(tmp_path, monkeypatch)
    monkeypatch.setattr(module, "gateway_service_running", lambda: True)
    monkeypatch.setattr(module, "RESTART_COOLDOWN_SECONDS", 0.0)
    monkeypatch.setattr(module, "api_listening", lambda: False)
    for _ in range(module.MAX_RESTART_ATTEMPTS):
        module.ensure_api_up()
    monkeypatch.setattr(module, "api_listening", lambda: True)
    module.ensure_api_up()
    monkeypatch.setattr(module, "api_listening", lambda: False)
    module.shell.clear()
    module.ensure_api_up()
    assert [c for c in module.shell if c[0] == "launchctl"]


def test_an_undecodable_byte_does_not_desync_the_offset(tmp_path, monkeypatch):
    """The log is read as bytes because a decoded chunk cannot be measured.

    One undecodable byte becomes a three-byte replacement character; measuring
    the decoded text back into an offset drifts, and every later read starts
    mid-line for good.
    """
    module, _, _ = load(tmp_path, monkeypatch)
    key, started = begin(module)
    stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(started + 5))
    path = tmp_path / "gateway.log"
    path.write_bytes(b"kaputtes byte \xff hier\n"
                     + real_line("Marie", f"{key}@s.whatsapp.net", "erste", stamp).encode()
                     + b"\n")
    monkeypatch.setattr(module, "GATEWAY_LOG", path)

    state = module.load()
    module.scan_gateway_log(state, time.time())
    assert state["standins"][key]["exchanges"] == 1

    # Der Offset muss exakt am Dateiende stehen, sonst wird der Anhang falsch gelesen.
    assert state["log"]["offset"] == path.stat().st_size
    with path.open("ab") as handle:
        handle.write(real_line("Marie", f"{key}@s.whatsapp.net", "zweite", stamp).encode() + b"\n")
    module.scan_gateway_log(state, time.time())
    assert [i["gist"] for i in state["standins"][key]["pending"]] == ["erste", "zweite"]


def test_a_standin_that_ends_quietly_still_says_it_ended(tmp_path, monkeypatch):
    """Splitting display from announcement must not swallow the closing line.

    With nothing pending the report *is* the closing line — announcing
    "nichts Neues" instead would tell him the opposite of what happened.
    """
    module, sent, _ = load(tmp_path, monkeypatch)
    key, now = begin(module)
    state = module.load()
    standin = state["standins"][key]
    module.flush(state, key, standin, now, speak=True, closing="Vertretung beendet.")

    _title, shown, spoken = sent[-1]
    assert "beendet" in shown and "beendet" in spoken


def test_a_quoted_report_still_announces_the_ending(tmp_path, monkeypatch):
    """Count instead of content, but the closing line survives."""
    module, sent, _ = load(tmp_path, monkeypatch)
    key, now = begin(module)
    state = module.load()
    standin = state["standins"][key]
    standin["pending"] = [{"at": now, "gist": "Befund positiv", "src": "log"}]
    module.flush(state, key, standin, now, speak=True, closing="Vertretung beendet.")

    _title, shown, spoken = sent[-1]
    assert "Befund positiv" in shown
    assert "Befund" not in spoken
    assert "beendet" in spoken


def test_a_poll_skips_rather_than_queue_behind_a_running_command(tmp_path, monkeypatch):
    """`start` holds the lock while it waits for the gateway.

    A minute-by-minute poll blocking on that would stack ticks; skipping costs
    nothing because the next one is sixty seconds away.
    """
    module, _, _ = load(tmp_path, monkeypatch)
    with module.state_lock() as first:
        assert first is True
        with module.state_lock(blocking=False) as second:
            assert second is False


def test_reply_to_id_inside_a_message_does_not_cut_the_gist(tmp_path, monkeypatch):
    """The tail is spelled out to the end of the record.

    A sender typing ` reply_to_id=` into their own message used to be able to
    move where the body ended.
    """
    module, _, _ = load(tmp_path, monkeypatch)
    key, started = begin(module)
    stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(started + 5))
    tricky = "schreib nicht ' reply_to_id=x rein"
    gateway_log(tmp_path, monkeypatch, module,
                [real_line("Marie", f"{key}@s.whatsapp.net", tricky, stamp)])

    state = module.load()
    module.scan_gateway_log(state, time.time())
    assert [i["gist"] for i in state["standins"][key]["pending"]] == [tricky]


def test_a_chat_that_is_not_shaped_like_a_whatsapp_id_is_ignored(tmp_path, monkeypatch):
    """The push name is logged unsanitised, so keep the comparison narrow."""
    module, _, _ = load(tmp_path, monkeypatch)
    key, started = begin(module)
    monkeypatch.setattr(module, "aliases", lambda _k: {key, "bogus"})
    stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(started + 5))
    gateway_log(tmp_path, monkeypatch, module,
                [real_line("Marie", "bogus@example.com", "untergeschoben", stamp)])

    state = module.load()
    module.scan_gateway_log(state, time.time())
    assert state["standins"][key].get("exchanges", 0) == 0


def test_giving_up_expires(tmp_path, monkeypatch):
    """Three failures mean this minute's problem, not a permanent verdict."""
    module, _, _ = load(tmp_path, monkeypatch)
    monkeypatch.setattr(module, "api_listening", lambda: False)
    monkeypatch.setattr(module, "gateway_service_running", lambda: True)
    monkeypatch.setattr(module, "RESTART_COOLDOWN_SECONDS", 0.0)
    for _ in range(module.MAX_RESTART_ATTEMPTS + 3):
        module.ensure_api_up()
    module.shell.clear()
    module.ensure_api_up()
    assert not [c for c in module.shell if c[0] == "launchctl"]   # aufgegeben

    # Ein späterer, wieder reparierbarer Ausfall bekommt sein Budget zurück.
    when, attempts = module.read_restart_stamp()
    module.note_restart_request(when - module.RESTART_GIVEUP_SECONDS - 1, attempts)
    module.shell.clear()
    module.ensure_api_up()
    assert [c for c in module.shell if c[0] == "launchctl"]


def test_a_report_uses_a_kind_the_bridge_accepts(tmp_path, monkeypatch):
    """The bridge answers an unknown kind with 400, and then nothing reaches the app.

    That is what happened: every report went out as "chat_standin", the bridge
    only knows NOTIFY_KINDS, and the app showed a silent stand-in through a live
    chat. Read the set from the bridge source, so the two cannot drift apart.
    """
    import ast
    import re
    load(tmp_path, monkeypatch)       # env into tmp; the stubbed module is not used
    spec = importlib.util.spec_from_file_location(
        "chat_standin_real", ROOT / "scripts" / "jarvis-chat-standin.py")
    real = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(real)
    posts = []
    monkeypatch.setattr(real, "post_json",
                        lambda url, payload, headers=None: posts.append((url, payload)) or True)

    real.deliver("Sofia", "fragt nach Samstag", speak=False)

    source = (ROOT / "bridge" / "jarvis_bridge.py").read_text()
    accepted = ast.literal_eval(re.search(r"^NOTIFY_KINDS = (\{.*\})$", source, re.M).group(1))
    kinds = [payload["kind"] for url, payload in posts if url == real.NOTIFY_URL]
    assert len(kinds) == 1 and kinds[0] in accepted


# ------------------------------------------------- live only once it can hear

def test_a_standin_is_not_live_before_a_bot_bridge_hears_the_contact(tmp_path, monkeypatch):
    """Self-chat mode, or bot mode without the contact on the list, still drops her messages."""
    module, sent, told = load(tmp_path, monkeypatch)
    run(module, "start", KEY, "--for", "1h", "--no-announce")
    bridge_says(module, "🌉 WhatsApp bridge listening on port 3000 (mode: self-chat)",
                "🔒 Allowed users: 4915129577496", "✅ WhatsApp connected!")
    run(module, "poll")
    assert module.load()["standins"][KEY]["live"] is False
    bridge_says(module, "🌉 WhatsApp bridge listening on port 3000 (mode: bot)",
                "🔒 Allowed users: 4915129577496", "✅ WhatsApp connected!")
    run(module, "poll")
    assert module.load()["standins"][KEY]["live"] is False
    assert not any("läuft" in item[1] for item in sent)
    bridge_says(module, *BOT_UP)
    run(module, "poll")
    assert module.load()["standins"][KEY]["live"] is True
    assert "läuft" in sent[-1][1] and told == []


def test_a_bridge_that_was_up_before_the_start_does_not_count(tmp_path, monkeypatch):
    """No timestamps in the bridge log: only lines written after the start are evidence."""
    module, sent, _ = load(tmp_path, monkeypatch)
    bridge_says(module, *BOT_UP)
    run(module, "start", KEY, "--for", "1h", "--no-announce")
    run(module, "poll")
    assert module.load()["standins"][KEY]["live"] is False


def test_receiving_that_never_comes_up_calls_the_standin_off(tmp_path, monkeypatch):
    module, sent, told = load(tmp_path, monkeypatch)
    run(module, "start", KEY, "--for", "1h", "--announce")
    state = module.load()
    state["standins"][KEY]["started"] -= module.LIVE_WAIT_SECONDS + 1
    module.save(state)
    run(module, "poll")
    assert module.load()["standins"] == {}
    assert told == [] and "nicht zustande" in sent[-1][1]
