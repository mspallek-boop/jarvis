"""Reading „Wo ist?“ — the parsing half, against labels the app really emitted.

The window read is UI automation and cannot run offline. The parsing can, and
it is where the guessing used to happen: JARVIS took a screenshot, ran vision
over it, and answered "Sophia wird gerade nicht angezeigt" while she was on
the screen.

Every fixture below is a verbatim capture from the accessibility tree of
FindMy on this Mac, including the two shapes it alternates between.
"""
import importlib.util
from pathlib import Path
import sys

import pytest

spec = importlib.util.spec_from_file_location(
    "jarvis_people", Path(__file__).resolve().parents[1] / "scripts/jarvis-people.py")
people = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = people
spec.loader.exec_module(people)


# Captured 2026-09-10. The bulleted entries are badges drawn on the map, the
# comma ones are the sidebar; the app repeats a badge several times.
CAPTURE = [
    "Wien • Angehalten", "Amore💓", "Wien • Angehalten", "Amore💓",
    "Wien • Angehalten", "Amore💓", "Wien • Angehalten", "Amore💓",
    "Antonspark", "Ich",
    "Wien , Angehalten", "5 km", "Leandertaler",
    "South Lake Tahoe, CA Vereinigte Staaten , Angehalten", "9.436 km", "Morris☝️🤓",
    "Wien , Angehalten", "0 km", "Amore💓",
    "Wien , Angehalten", "4 km", "Leonie Kochgasse",
]


def by_name(rows):
    return {row["name"]: row for row in rows}


def test_everyone_in_the_sidebar_is_found():
    found = by_name(people.parse(CAPTURE))
    assert set(found) == {"Ich", "Leandertaler", "Morris☝️🤓", "Amore💓", "Leonie Kochgasse"}


def test_place_distance_and_status_are_kept_apart():
    row = by_name(people.parse(CAPTURE))["Leandertaler"]
    assert row["ort"] == "Wien"
    assert row["entfernung"] == "5 km"
    assert row["stand"] == "Angehalten"


def test_a_place_with_its_own_commas_survives():
    """"South Lake Tahoe, CA Vereinigte Staaten" has commas of its own, and the
    status is separated by one too. Splitting on the first would have cut the
    town in half."""
    row = by_name(people.parse(CAPTURE))["Morris☝️🤓"]
    assert row["ort"].startswith("South Lake Tahoe")
    assert row["entfernung"] == "9.436 km"


def test_the_map_badges_are_not_counted_as_people():
    """The same person appears four times as a badge and once as a row."""
    rows = [row for row in people.parse(CAPTURE) if row["name"] == "Amore💓"]
    assert len(rows) == 1
    assert rows[0]["entfernung"] == "0 km"


def test_the_user_has_no_distance_to_himself():
    row = by_name(people.parse(CAPTURE))["Ich"]
    assert row["ort"] == "Antonspark"


def test_the_other_shape_the_tree_takes_parses_too():
    """Captured a minute later: the labels reflowed, a place got doubled, and
    "Angehalten" had become "Jetzt". Anchoring on the distance survives it."""
    later = [
        "Wien • Jetzt", "Amore💓", "Antonspark", "Ich",
        "Wien , Jetzt", "5 km", "Leandertaler",
        "South Lake Tahoe, CA Vereinigte Staaten , Jetzt", "9.436 km", "Morris☝️🤓",
        "0 km", "Amore💓", "Wien , Jetzt", "Wien , Jetzt", "4 km", "Vivi",
    ]
    found = by_name(people.parse(later))
    assert "Vivi" in found and found["Vivi"]["entfernung"] == "4 km"
    assert found["Leandertaler"]["ort"] == "Wien"


def test_nobody_sharing_is_not_an_error():
    assert people.parse(["Antonspark", "Ich"])[0]["name"] == "Ich"
    assert people.parse([]) == []
