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
    spec = importlib.util.spec_from_file_location(
        "chat_standin", ROOT / "scripts" / "jarvis-chat-standin.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["chat_standin"] = module
    spec.loader.exec_module(module)
    # Nothing in a test may reach the bridge, WhatsApp, the speaker or the
    # mode switch.
    sent, told, shell = [], [], []
    module.deliver = lambda title, text, speak: sent.append((title, text))
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


def test_announcing_tells_the_contact_once_and_names_the_duration(tmp_path, monkeypatch):
    module, _, told = load(tmp_path, monkeypatch)
    assert run(module, "start", KEY, "--name", "Marie", "--for", "2h", "--announce") == 0
    assert len(told) == 1
    text = told[0][1]
    assert "KI-Assistent" in text and "2 Stunden" in text and "Marlon" in text
    assert module.load()["standins"][KEY]["announced"] is True


def test_not_announcing_says_nothing_to_the_contact(tmp_path, monkeypatch):
    module, _, told = load(tmp_path, monkeypatch)
    assert run(module, "start", KEY, "--for", "1h", "--no-announce") == 0
    assert told == []
    assert module.load()["standins"][KEY]["announced"] is False


def test_a_failed_announcement_cancels_the_whole_standin(tmp_path, monkeypatch):
    """Promising transparency and not delivering it is worse than not offering."""
    module, _, _ = load(tmp_path, monkeypatch)
    module.tell_contact = lambda key, text: False
    assert run(module, "start", KEY, "--for", "1h", "--announce") == 1
    assert module.load()["standins"] == {}


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
