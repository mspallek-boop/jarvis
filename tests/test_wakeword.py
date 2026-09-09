"""The wake-word trigger: does one „Hey JARVIS" wake him once?"""
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load():
    """Import the script without importing the audio stack it only needs at run time."""
    spec = importlib.util.spec_from_file_location(
        "wakeword", ROOT / "scripts" / "jarvis-wakeword.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["wakeword"] = module
    spec.loader.exec_module(module)
    return module


def test_a_score_below_the_threshold_wakes_nothing():
    trigger = load().Trigger(threshold=0.5, cooldown=8)
    assert trigger.should_fire(0.49, now=100) is False


def test_one_utterance_wakes_him_once():
    """A spoken wake word crosses the threshold for a run of frames, and JARVIS's
    own answer is the next thing the microphone hears. Both are the same
    mistake — waking something already awake — and one silence covers both."""
    trigger = load().Trigger(threshold=0.5, cooldown=8)
    assert trigger.should_fire(0.9, now=100) is True
    for offset in (0.1, 0.4, 1.0, 5.0, 7.9):
        assert trigger.should_fire(0.9, now=100 + offset) is False


def test_he_can_be_woken_again_after_the_cooldown():
    trigger = load().Trigger(threshold=0.5, cooldown=8)
    trigger.should_fire(0.9, now=100)
    assert trigger.should_fire(0.9, now=108) is True


def test_a_quiet_run_never_starts_the_cooldown():
    """A near miss must not block the wake word that follows it."""
    trigger = load().Trigger(threshold=0.5, cooldown=8)
    assert trigger.should_fire(0.2, now=100) is False
    assert trigger.should_fire(0.9, now=100.1) is True


@pytest.mark.parametrize("score", [0.5, 0.75, 1.0])
def test_the_threshold_is_inclusive(score):
    assert load().Trigger(threshold=0.5, cooldown=8).should_fire(score, now=1) is True


def test_the_url_says_exactly_one_thing():
    """A URL scheme is open to anything on the machine that can call `open`, so
    the only thing it may express is "start listening"."""
    source = (ROOT / "scripts" / "jarvis-wakeword.py").read_text()
    assert "jarvis://wake" in source
    # Every mention, comments included, is the same one thing.
    assert source.count("jarvis://") == source.count("jarvis://wake")
