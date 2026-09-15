#!/usr/bin/env python3
"""Where a spoken turn's time goes, read from the bridge's Messmodus log.

Switch the measurement on with `touch ~/.hermes/voice-timing-on`, talk to
JARVIS, then run this. Every span subtracts two events recorded on the same
clock — bridge events from bridge events, app events from app events — because
the phone's monotonic clock and the Mac's have nothing to do with each other.

Turns with and without tools are reported apart: a web search turns a
four-second answer into a fifteen-second one, and one median over both
describes neither. Quantiles are taken per span over the turns that have both
events; they are never added up into a total.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_LOG = Path.home() / ".hermes" / "logs" / "voice-timing.jsonl"

# name, clock, start event, which occurrence, end event(s), which occurrence.
# A tuple of end events means: the first of them that the turn has.
SPANS = (
    ("bridge_queue", "bridge", "received", "first", "lock_acquired", "first"),
    ("hermes_first_token", "bridge", "hermes_request", "first", "text_segment_start", "first"),
    # When the answer arrives only with assistant.completed there is no
    # text_forwarded; the app then gets it with done.
    ("received_to_answer_text", "bridge", "received", "first", ("text_forwarded", "done"), "first"),
    ("answer_segment_generation", "bridge", "text_segment_start", "last", "assistant_completed", "first"),
    ("bridge_turn_total", "bridge", "received", "first", "done", "first"),
    ("tts_first_audio", "bridge", "tts_received", "first", "tts_first_audio", "first"),
    ("app_endpoint_wait", "app", "speech_end", "first", "endpoint_fired", "first"),
    ("app_request_to_first_text", "app", "request_sent", "first", "first_text_frame", "first"),
    ("app_text_to_first_sentence", "app", "first_text_frame", "first", "first_sentence_enqueued", "first"),
    ("app_sentence_to_sound", "app", "first_sentence_enqueued", "first", "playback_started", "first"),
    ("perceived_latency", "app", "speech_end", "first", "playback_started", "first"),
    ("bargein_to_silence", "app", "bargein_detected", "first", "audio_stopped", "first"),
)
# A text segment that started before the last tool call was narration, not the
# answer, so it says nothing about how long the answer took to generate.
AFTER_LAST_TOOL = {"answer_segment_generation"}


@dataclass
class Run:
    events: dict = field(default_factory=lambda: defaultdict(list))
    tools: int = 0


def collect(records: list[dict]) -> dict[str, Run]:
    runs: dict[str, Run] = defaultdict(Run)
    for record in records:
        run, src, event, at = (record.get(key) for key in ("run", "src", "event", "t"))
        if not (isinstance(run, str) and isinstance(src, str) and isinstance(event, str)
                and isinstance(at, (int, float)) and not isinstance(at, bool)):
            continue
        # The first sentence is the one the user is waiting for; later ones
        # overlap playback and say nothing about perceived latency.
        if event.startswith("tts_") and record.get("seq", 0) != 0:
            continue
        runs[run].events[(src, event)].append(at)
        if src == "bridge" and event == "tool_started":
            runs[run].tools += 1
    return dict(runs)


def _times(run: Run, clock: str, events) -> list[float]:
    for event in (events,) if isinstance(events, str) else events:
        found = run.events.get((clock, event))
        if found:
            return found
    return []


def span_values(runs: dict[str, Run]) -> dict[str, dict[str, float]]:
    values: dict[str, dict[str, float]] = {name: {} for name, *_ in SPANS}
    for run_id, run in runs.items():
        last_tool = max(run.events.get(("bridge", "tool_started")) or [float("-inf")])
        for name, clock, start, start_pick, end, end_pick in SPANS:
            starts, ends = _times(run, clock, start), _times(run, clock, end)
            if not starts or not ends:
                continue
            begin = min(starts) if start_pick == "first" else max(starts)
            finish = min(ends) if end_pick == "first" else max(ends)
            if name in AFTER_LAST_TOOL and begin < last_tool:
                continue
            if finish >= begin:
                values[name][run_id] = round(finish - begin, 1)
    return values


def quantile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(q * (len(ordered) - 1))))]


def _cell(values: list[float]) -> str:
    if not values:
        return f"{'–':>6} {'':6} {0:3d}"
    return f"{quantile(values, .5) / 1000:6.2f} {quantile(values, .9) / 1000:6.2f} {len(values):3d}"


def read_log(path: Path) -> list[dict]:
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def print_summary(runs: dict[str, Run]) -> None:
    values = span_values(runs)
    with_tools = {run_id for run_id, run in runs.items() if run.tools}
    print(f"Turns: {len(runs)} (mit Tools: {len(with_tools)}, ohne: {len(runs) - len(with_tools)})")
    print("Sekunden: p50 p90 n")
    print(f"{'Span':28} {'alle':>17} | {'ohne Tools':>17} | {'mit Tools':>17}")
    for name, *_ in SPANS:
        per_run = values[name]
        every = list(per_run.values())
        plain = [v for run_id, v in per_run.items() if run_id not in with_tools]
        tooled = [v for run_id, v in per_run.items() if run_id in with_tools]
        print(f"{name:28} {_cell(every)} | {_cell(plain)} | {_cell(tooled)}")


def print_timeline(run: Run) -> None:
    for clock in ("app", "bridge"):
        points = sorted((at, event) for (src, event), times in run.events.items()
                        if src == clock for at in times)
        if not points:
            continue
        origin = points[0][0]
        print(f"[{clock}]")
        for at, event in points:
            print(f"  +{(at - origin) / 1000:7.3f} s  {event}")
    print(f"Tools: {run.tools}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Latenz pro Turn aus dem Messmodus-Log")
    parser.add_argument("log", nargs="?", type=Path, default=DEFAULT_LOG)
    parser.add_argument("--run", help="die Events eines Turns als Zeitleiste zeigen")
    args = parser.parse_args()
    if not args.log.exists():
        raise SystemExit(f"Kein Log unter {args.log}. Messmodus an? touch ~/.hermes/voice-timing-on")
    runs = collect(read_log(args.log))
    if args.run:
        if args.run not in runs:
            raise SystemExit(f"Turn {args.run} nicht im Log")
        print_timeline(runs[args.run])
    else:
        print_summary(runs)


if __name__ == "__main__":
    main()
