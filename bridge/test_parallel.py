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
