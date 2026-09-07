"""jarvis-contact.sh: ambiguity must be impossible to mistake for success."""
import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "jarvis-contact.sh"


@pytest.fixture
def contacts(tmp_path):
    """A cache with two people called Rici and one unambiguous name."""
    cache = tmp_path / "contacts.cache.tsv"
    cache.write_text(
        "Rici Mayer\t\t+49 151 1111111\t491511111111\n"
        "Rici Berger\t\t+49 170 2222222\t491702222222\n"
        "Marcel Richter\t\t+43 677 3333333\t436773333333\n")
    return cache


def run(cache, *args):
    env = {**os.environ, "HOME": str(cache.parent)}
    (cache.parent / ".hermes").mkdir(exist_ok=True)
    (cache.parent / ".hermes" / "contacts.cache.tsv").write_text(cache.read_text())
    done = subprocess.run(["/bin/zsh", str(SCRIPT), *args],
                          capture_output=True, text=True, env=env, timeout=30)
    return done.returncode, done.stdout


def test_several_matches_never_look_like_success(contacts):
    """Exit 0 on an ambiguous name is how a message reaches a stranger."""
    code, out = run(contacts, "rici")
    assert code == 10
    assert "MEHRDEUTIG" in out
    assert "1)" in out and "2)" in out


def test_a_single_match_is_usable_straight_away(contacts):
    code, out = run(contacts, "Marcel Richter")
    assert code == 0
    assert out.count("@s.whatsapp.net") == 1
    assert "436773333333@s.whatsapp.net" in out


def test_pick_selects_from_the_list_that_was_shown(contacts):
    _, listing = run(contacts, "rici")
    first = run(contacts, "--pick", "1", "rici")
    second = run(contacts, "--pick", "2", "rici")
    assert first[0] == second[0] == 0
    assert first[1] != second[1]
    for chosen in (first[1], second[1]):
        assert chosen.strip() in listing.replace(" 1) ", "").replace(" 2) ", "")


def test_picking_past_the_end_is_refused(contacts):
    assert run(contacts, "--pick", "9", "rici")[0] == 2


def test_a_non_numeric_pick_is_refused(contacts):
    assert run(contacts, "--pick", "zwei", "rici")[0] == 2


def test_nothing_found_says_so(contacts):
    code, out = run(contacts, "gibtesnicht")
    assert code == 1
    assert "@s.whatsapp.net" not in out


def test_a_dictated_number_still_resolves_directly(contacts):
    code, out = run(contacts, "+49 151 1111111")
    assert code == 0
    assert "491511111111@s.whatsapp.net" in out
    assert "Rici Mayer" in out          # named, so a misheard digit shows up


def test_a_contact_without_a_nickname_keeps_its_number(tmp_path):
    """Two consecutive tabs are one separator to `read`, and a contact with no
    nickname has exactly that — the fields shift and the chat id comes out
    wrong. On the gateway the cache is the only path, so this decides whether a
    message reaches the right person."""
    cache = tmp_path / "contacts.cache.tsv"
    cache.write_text("Ohne Spitzname\t\t+49 151 9999999\t491519999999\n")
    code, out = run(cache, "Ohne Spitzname")
    assert code == 0
    assert "491519999999@s.whatsapp.net" in out
    assert "+49 151 9999999" in out
