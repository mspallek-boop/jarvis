#!/usr/bin/env python3
"""Listen for „Hey JARVIS" and wake the app, hands free.

    jarvis-wakeword.py run          # what launchd calls
    jarvis-wakeword.py selftest     # model loads, audio device opens

Why a detector rather than the recogniser that is already there: Apple's
`SFSpeechRecognizer` would have to run permanently and would turn everything
within earshot into text. openWakeWord never transcribes — it scores 80 ms of
audio against one small model and forgets it. The expensive, transcribing part
only starts once the app has been woken, which is the whole reason the cheap
part exists.

It holds the microphone only while JARVIS is actually running. That is what the
user asked for, and it is also why the orange recording dot is not simply on all
day: with the app closed there is nothing to wake, so there is nothing to listen
for either.

On a hit it runs `open -g jarvis://wake`, which Launch Services delivers to the
running app. No port, no socket, no accessibility permission — and the URL can
express exactly one thing, "start listening". See AppDelegate.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time

MODEL = os.environ.get("JARVIS_WAKE_MODEL", "hey_jarvis")
# openWakeWord's own suggested operating point. Lower catches more and lets the
# television wake him; higher makes you say it twice.
THRESHOLD = float(os.environ.get("JARVIS_WAKE_THRESHOLD", "0.5"))
# One utterance produces a run of frames over the threshold, and JARVIS's own
# answer is the next thing the microphone hears. Both are the same mistake —
# waking something that is already awake — so both are covered by one silence.
COOLDOWN_SECONDS = float(os.environ.get("JARVIS_WAKE_COOLDOWN", "8"))
# openWakeWord is trained on 16 kHz mono, 1280 samples (80 ms) at a time.
SAMPLE_RATE = 16000
BLOCK = 1280
APP_BINARY = "/Applications/JARVIS.app/Contents/MacOS/JARVIS"
# How often to look for the app while it is not running. Long enough that the
# check costs nothing, short enough that starting JARVIS makes the wake word
# work without thinking about it.
IDLE_POLL_SECONDS = 5.0


def app_is_running() -> bool:
    try:
        return subprocess.run(["/usr/bin/pgrep", "-f", APP_BINARY],
                              capture_output=True, timeout=5).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def wake() -> bool:
    """Hand the app the one thing this process is allowed to say."""
    try:
        return subprocess.run(["/usr/bin/open", "-g", "jarvis://wake"],
                              capture_output=True, timeout=10).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


class Trigger:
    """Decides whether a score means "wake him", keeping the cooldown.

    Pure and separate from the audio so it can be tested without a microphone
    and without saying anything out loud.
    """

    def __init__(self, threshold: float = THRESHOLD, cooldown: float = COOLDOWN_SECONDS):
        self.threshold = threshold
        self.cooldown = cooldown
        # "never fired", not "fired at the epoch": with a plain 0 a freshly
        # started detector is inside its own cooldown for any small clock.
        self.last_fired = float("-inf")

    def should_fire(self, score: float, now: float) -> bool:
        if score < self.threshold:
            return False
        if now - self.last_fired < self.cooldown:
            return False
        self.last_fired = now
        return True


def run() -> int:
    import numpy as np
    import sounddevice as sd
    from openwakeword.model import Model

    # onnx, not tflite: openWakeWord pins tflite-runtime to Linux.
    model = Model(wakeword_models=[MODEL], inference_framework="onnx")
    trigger = Trigger()
    print(f"Weckwort aktiv: {MODEL} (Schwelle {trigger.threshold})", flush=True)

    while True:
        if not app_is_running():
            # Nothing to wake, so nothing to listen to — and no recording dot.
            time.sleep(IDLE_POLL_SECONDS)
            continue
        try:
            with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16",
                                blocksize=BLOCK) as stream:
                print("Mikrofon offen, JARVIS läuft.", flush=True)
                while app_is_running():
                    frame, overflowed = stream.read(BLOCK)
                    if overflowed:
                        continue
                    scores = model.predict(frame.flatten())
                    score = float(scores.get(MODEL, 0.0))
                    if trigger.should_fire(score, time.time()):
                        print(f'„Hey JARVIS" erkannt ({score:.2f}) — wecke die App.', flush=True)
                        wake()
                        # Drop what was buffered during the utterance so the tail
                        # of it cannot score again on the next read.
                        model.reset()
                print("JARVIS ist weg, Mikrofon wieder frei.", flush=True)
        except Exception as error:            # sounddevice raises a lot of shapes
            print(f"Audio-Fehler: {error}", file=sys.stderr, flush=True)
            time.sleep(IDLE_POLL_SECONDS)


def selftest() -> int:
    from openwakeword.model import Model
    model = Model(wakeword_models=[MODEL], inference_framework="onnx")
    print("Modell geladen:", list(model.models.keys()))
    import sounddevice as sd
    device = sd.query_devices(kind="input")
    print("Eingabegerät:", device["name"])
    print("JARVIS läuft:", app_is_running())
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("run", help="dauerhaft lauschen (launchd)").set_defaults(func=lambda a: run())
    sub.add_parser("selftest", help="Modell und Mikrofon prüfen").set_defaults(func=lambda a: selftest())
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
