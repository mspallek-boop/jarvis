"""Parallel turns: a second task must start, not queue — when asked for."""
import threading
import time
from types import SimpleNamespace

import pytest
import jarvis_bridge as bridge


def client_with_slow_turn(seconds=0.4):
    """A client whose turn takes real time, so overlap is observable."""
    client = bridge.HermesClient(SimpleNamespace())
    started, order = [], []

    def once(text, conversation, force_new, client_run_id="", **kwargs):
        started.append((conversation, time.monotonic()))
        time.sleep(seconds)
        order.append(conversation)
        return {"text": text, "tools": [], "run_id": "r"}

    client._chat_once = once
    client._started, client._order = started, order
    return client


def run_together(client, count, conversation="conv", parallel=False):
    threads, results, errors = [], {}, []

    def worker(index):
        try:
            results[index] = client.chat(f"m{index}", conversation,
                                         f"run-{index}", parallel=parallel)
        except Exception as exc:            # surfaced by the assertions below
            errors.append(exc)

    begin = time.monotonic()
    for index in range(count):
        thread = threading.Thread(target=worker, args=(index,))
        thread.start()
        threads.append(thread)
        time.sleep(0.02)                    # keep the request order deterministic
    for thread in threads:
        thread.join(timeout=30)
    assert not errors, errors
    return results, time.monotonic() - begin


def test_without_the_flag_turns_still_queue():
    """The default must not change: two turns of one thought stay in order."""
    client = client_with_slow_turn()
    results, elapsed = run_together(client, 2)
    assert elapsed >= 0.8                       # 2 x 0.4s, serial
    assert {r["conversation"] for r in results.values()} == {"conv"}


def test_the_flag_lets_a_second_turn_start_immediately():
    client = client_with_slow_turn()
    results, elapsed = run_together(client, 2, parallel=True)
    assert elapsed < 0.7                        # overlapped, not 0.8s
    assert results[0]["conversation"] == "conv"
    assert results[1]["conversation"] == "conv#2"


def test_each_parallel_turn_gets_its_own_session():
    client = client_with_slow_turn(0.3)
    results, _ = run_together(client, 4, parallel=True)
    names = [results[i]["conversation"] for i in range(4)]
    assert names == ["conv", "conv#2", "conv#3", "conv#4"]
    assert len(set(names)) == 4                 # four sessions, no sharing


def test_beyond_the_cap_a_turn_queues_rather_than_opening_sessions_forever():
    client = client_with_slow_turn(0.25)
    results, _ = run_together(client, bridge.MAX_PARALLEL_CONVERSATIONS + 1,
                              parallel=True)
    names = [results[i]["conversation"] for i in range(len(results))]
    assert len(set(names)) == bridge.MAX_PARALLEL_CONVERSATIONS
    assert names[-1] == "conv"                  # waited for the first lane


def test_a_lane_is_reused_once_it_is_free():
    client = client_with_slow_turn(0.05)
    first = client.chat("a", "conv", "run-a", parallel=True)
    second = client.chat("b", "conv", "run-b", parallel=True)
    assert first["conversation"] == second["conversation"] == "conv"


def test_the_run_board_shows_where_a_turn_really_runs():
    """A task shown under the wrong conversation is worse than none."""
    client = bridge.HermesClient(SimpleNamespace())
    seen = {}
    blocked = threading.Event()

    def once(text, conversation, force_new, client_run_id="", **kwargs):
        if client_run_id == "run-1":
            blocked.wait(timeout=10)
        else:
            seen.update({run["client_run_id"]: run["conversation"]
                         for run in client.active_runs()})
        return {"text": text, "tools": [], "run_id": "r"}

    client._chat_once = once
    first = threading.Thread(target=lambda: client.chat("a", "conv", "run-1"))
    first.start()
    time.sleep(0.1)
    client.chat("b", "conv", "run-2", parallel=True)
    blocked.set()
    first.join(timeout=10)
    assert seen["run-2"] == "conv#2"
    assert seen["run-1"] == "conv"


def test_a_failing_turn_still_frees_its_lane():
    client = bridge.HermesClient(SimpleNamespace())

    def once(*args, **kwargs):
        raise RuntimeError("kaputt")

    client._chat_once = once
    for index in range(bridge.MAX_PARALLEL_CONVERSATIONS + 2):
        with pytest.raises(RuntimeError):
            client.chat("m", "conv", f"run-{index}", parallel=True)
    # Nothing leaked: a fresh turn still gets the main lane.
    client._chat_once = lambda text, conversation, *a, **k: {
        "text": text, "tools": [], "run_id": "r"}
    assert client.chat("m", "conv", "run-last", parallel=True)["conversation"] == "conv"


# ------------------------------------------- a parallel lane keeps the thread

def client_with_history(messages):
    """A client whose main conversation already has a transcript."""
    client = bridge.HermesClient(SimpleNamespace(state_path=None))
    client._load_state = lambda: {"conv": "session-main"}
    sent = []

    class Response:
        def __init__(self, payload):
            self._payload = payload
        def read(self):
            import json as _json
            return _json.dumps(self._payload).encode()
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False

    client._request = lambda method, path, *a, **k: Response({"data": messages})
    client._chat_once = lambda text, conversation, *a, **k: (
        sent.append((conversation, text)) or {"text": "ok", "tools": [], "run_id": "r"})
    client._sent = sent
    return client


HISTORY = [{"role": "user", "content": "Recherchiere bitte Flüge nach Tokio"},
           {"role": "assistant", "content": "Ich sehe mir das an."},
           {"role": "tool", "content": "{\"raw\": \"tool noise\"}"}]


def test_a_side_lane_is_told_what_was_just_discussed():
    """Otherwise a new task starts blind — "he forgets everything"."""
    client = client_with_history(HISTORY)
    client._chat_once = lambda text, conversation, *a, **k: (
        client._sent.append((conversation, text)) or {"text": "ok", "tools": [], "run_id": "r"})
    # Occupy the main lane so the next turn is forced into a side lane.
    client._lock_for("conv").acquire()
    client.chat("Schreib Rici", "conv", "run-2", parallel=True)
    conversation, text = client._sent[-1]
    assert conversation == "conv#2"
    assert "Tokio" in text and "Schreib Rici" in text
    assert "tool noise" not in text          # tool traffic is noise out of context


def test_the_main_conversation_never_gets_a_preamble():
    client = client_with_history(HISTORY)
    client.chat("Was war das nochmal?", "conv", "run-1")
    conversation, text = client._sent[-1]
    assert conversation == "conv"
    assert text == "Was war das nochmal?"    # its own session already remembers


def test_context_failures_never_block_the_turn():
    client = client_with_history(HISTORY)
    client._request = lambda *a, **k: (_ for _ in ()).throw(OSError("hermes weg"))
    client._lock_for("conv").acquire()
    result = client.chat("Neue Aufgabe", "conv", "run-2", parallel=True)
    assert result["conversation"] == "conv#2"
    assert client._sent[-1][1] == "Neue Aufgabe"


def test_the_preamble_is_bounded():
    long_history = [{"role": "user", "content": "x" * 5000} for _ in range(20)]
    client = client_with_history(long_history)
    client._lock_for("conv").acquire()
    client.chat("kurz", "conv", "run-2", parallel=True)
    assert len(client._sent[-1][1]) < 3000
