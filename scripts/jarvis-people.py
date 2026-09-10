#!/usr/bin/env python3
"""Where the people are, out of „Wo ist?“.

    jarvis-people.py                 # alle, wie sie in der Seitenleiste stehen
    jarvis-people.py Sofia           # eine Person
    jarvis-people.py --json

Why this exists as a script rather than as something JARVIS improvises:
without it he took a screenshot, ran it through vision, and guessed — which is
why he answered "Sophia wird gerade nicht angezeigt" while she was on the
screen.

Why it reads the interface rather than a file: the friends' locations live in
`~/Library/Caches/com.apple.findmy.fmfcore/FriendCacheData.data`, and that file
holds exactly two keys — `signature` and `encryptedData`. Apple encrypts them
at rest. There is no readable store, so the window is the only source.

Three things about that window, all learned the hard way:

- Its accessibility tree is only populated while the app is frontmost and
  freshly activated. Read it a second later from a background app and every
  element is gone. So activating and reading happen in one AppleScript pass.
- The tree reshapes between reads: the same rows appear as groups of three
  texts one moment and as a flat run the next. Grouping by container was
  unreliable, so the flat list is parsed instead, anchored on the distance.
- It updates live. "Angehalten" becomes "Jetzt", labels change under you.
  Anything read here is a snapshot and is reported as one.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys

# The sidebar separates place from status with a comma; the badges drawn on the
# map use a bullet. Only the sidebar is a complete row, so the bullet ones are
# dropped rather than counted twice.
BADGE = "•"
DISTANCE = re.compile(r"^\s*[\d.,]+\s*(?:km|m|mi|ft)\s*$", re.I)

READ_SCRIPT = r'''
-- `reopen` is what the Dock icon does: activate alone leaves a closed window
-- closed, and a closed window has no tree to read.
tell application "FindMy"
  activate
  reopen
end tell
delay %(settle)s
tell application "System Events" to tell process "FindMy"
  repeat with wait from 1 to 10
    if (count of windows) > 0 then exit repeat
    delay 0.5
  end repeat
  if (count of windows) = 0 then return "KEIN_FENSTER"
  set out to ""
  repeat with e in (entire contents of window 1)
    try
      if role of e is "AXStaticText" then
        set d to description of e as string
        if d is not "missing value" and d is not "" then set out to out & d & "\n"
      end if
    end try
  end repeat
  return out
end tell
'''


def read_window(settle: float) -> list[str]:
    """One pass: activate, let it draw, read every label it has."""
    done = subprocess.run(
        ["osascript", "-e", READ_SCRIPT % {"settle": settle}],
        capture_output=True, text=True, timeout=90)
    if done.returncode != 0:
        raise RuntimeError(done.stderr.strip().splitlines()[-1] if done.stderr.strip()
                           else "osascript ohne Ausgabe")
    text = done.stdout.strip()
    if text == "KEIN_FENSTER":
        raise RuntimeError("„Wo ist?“ hat kein Fenster offen.")
    return [line.strip() for line in text.splitlines() if line.strip()]


def parse(labels: list[str]) -> list[dict]:
    """Assemble rows around the distance, because that is the only token whose
    shape is unmistakable.

    A sidebar row reads place, distance, name. `Ich` has no distance and comes
    as place then name, so it is picked up separately.
    """
    people: list[dict] = []
    seen: set[str] = set()
    for index, label in enumerate(labels):
        if not DISTANCE.match(label):
            continue
        name = labels[index + 1] if index + 1 < len(labels) else ""
        if not name or DISTANCE.match(name) or BADGE in name:
            continue
        place = ""
        for back in range(index - 1, max(index - 3, -1), -1):
            candidate = labels[back]
            if DISTANCE.match(candidate) or BADGE in candidate:
                continue
            place = candidate
            break
        if name in seen:
            continue
        seen.add(name)
        where, _, status = place.partition(",")
        people.append({"name": name,
                       "ort": where.strip(" ,"),
                       "stand": status.strip(" ,"),
                       "entfernung": label.strip()})
    # "Ich" carries no distance, so the loop above never reaches it.
    for index, label in enumerate(labels):
        if label == "Ich" and index > 0 and "Ich" not in seen:
            people.insert(0, {"name": "Ich", "ort": labels[index - 1].strip(" ,"),
                              "stand": "", "entfernung": "0 km"})
            break
    return people


def describe(person: dict) -> str:
    bits = [person["name"] + ":", person["ort"] or "unbekannt"]
    if person["entfernung"] and person["name"] != "Ich":
        bits.append("· " + person["entfernung"] + " entfernt")
    if person["stand"]:
        bits.append("· " + person["stand"])
    return " ".join(bits)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("name", nargs="?", default="",
                        help="nur diese Person (Teilstring reicht)")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--settle", type=float, default=2.0,
                        help="Sekunden, die die App zum Zeichnen bekommt")
    args = parser.parse_args(argv)

    try:
        people = parse(read_window(args.settle))
    except (OSError, subprocess.SubprocessError, RuntimeError) as error:
        print(f"„Wo ist?“ nicht lesbar: {error}", file=sys.stderr)
        return 1

    if args.name:
        wanted = args.name.casefold()
        people = [p for p in people if wanted in p["name"].casefold()]
        if not people:
            print(f"{args.name} steht nicht in „Wo ist?“. "
                  f"Wer dort steht, zeigt der Aufruf ohne Namen.", file=sys.stderr)
            return 1

    if args.json:
        print(json.dumps(people, ensure_ascii=False, indent=2))
        return 0
    if not people:
        print("Niemand teilt gerade seinen Standort.")
        return 0
    for person in people:
        print(describe(person))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
