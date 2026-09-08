"""Reading WhatsApp Desktop's store: right names, right kinds, never a write."""
import importlib.util
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
COCOA_EPOCH = 978307200


def stamp(moment):
    return moment.timestamp() - COCOA_EPOCH


def build_store(path):
    """The columns the script actually touches, and no more — a fixture that
    mirrored all 34 tables would rot faster than the code it guards."""
    db = sqlite3.connect(path)
    db.executescript("""
        CREATE TABLE ZWACHATSESSION (
            Z_PK INTEGER PRIMARY KEY, ZPARTNERNAME TEXT, ZUNREADCOUNT INTEGER,
            ZLASTMESSAGEDATE REAL, ZHIDDEN INTEGER, ZARCHIVED INTEGER,
            ZGROUPINFO INTEGER);
        CREATE TABLE ZWAMESSAGE (
            Z_PK INTEGER PRIMARY KEY, ZTEXT TEXT, ZMESSAGETYPE INTEGER,
            ZMESSAGEDATE REAL, ZISFROMME INTEGER, ZCHATSESSION INTEGER,
            ZGROUPMEMBER INTEGER, ZPUSHNAME TEXT);
        CREATE TABLE ZWAGROUPMEMBER (
            Z_PK INTEGER PRIMARY KEY, ZCONTACTNAME TEXT, ZFIRSTNAME TEXT,
            ZMEMBERJID TEXT);
        CREATE TABLE ZWAPROFILEPUSHNAME (Z_PK INTEGER PRIMARY KEY,
            ZJID TEXT, ZPUSHNAME TEXT);
    """)
    now = datetime.now()
    db.executemany(
        "INSERT INTO ZWACHATSESSION VALUES (?,?,?,?,?,?,?)", [
            (1, "Andi", 2, stamp(now - timedelta(minutes=5)), 0, 0, None),
            (2, "Baugruppe", 1, stamp(now - timedelta(hours=2)), 0, 0, 77),
            (3, "Gelesen", 0, stamp(now - timedelta(days=1)), 0, 0, None),
            (4, "Archiviert", 9, stamp(now), 0, 1, None),
            (5, "Versteckt", 9, stamp(now), 1, 0, None),
        ])
    # ZCONTACTNAME empty on purpose: the real store leaves it blank and the
    # name has to come from ZWAPROFILEPUSHNAME via the @lid identifier.
    db.execute("INSERT INTO ZWAGROUPMEMBER VALUES (10, '', '', '4711@lid')")
    db.execute("INSERT INTO ZWAGROUPMEMBER VALUES (11, 'Sabina', '', '4712@lid')")
    db.execute("INSERT INTO ZWAPROFILEPUSHNAME VALUES (1, '4711@lid', 'María')")
    db.executemany(
        "INSERT INTO ZWAMESSAGE VALUES (?,?,?,?,?,?,?,?)", [
            (1, "erste", 0, stamp(now - timedelta(minutes=9)), 0, 1, None, None),
            (2, "meine antwort", 0, stamp(now - timedelta(minutes=7)), 1, 1, None, None),
            (3, "zweite", 0, stamp(now - timedelta(minutes=6)), 0, 1, None, None),
            (4, "dritte", 0, stamp(now - timedelta(minutes=5)), 0, 1, None, None),
            (5, None, 1, stamp(now - timedelta(hours=2)), 0, 2, 10, "base64junk"),
            (6, "trat bei", 6, stamp(now - timedelta(hours=3)), 0, 2, 11, None),
        ])
    db.commit()
    db.close()


@pytest.fixture
def script(tmp_path, monkeypatch):
    store = tmp_path / "ChatStorage.sqlite"
    build_store(store)
    monkeypatch.setenv("JARVIS_WA_STORE", str(store))
    spec = importlib.util.spec_from_file_location(
        "wa_read", ROOT / "scripts" / "jarvis-whatsapp-read.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["wa_read"] = module
    spec.loader.exec_module(module)
    return module, store


def run(module, *argv, monkeypatch=None):
    import io
    import contextlib
    out = io.StringIO()
    sys.argv = ["jarvis-whatsapp-read.py", *argv]
    with contextlib.redirect_stdout(out):
        module.main()
    return out.getvalue()


def test_unread_lists_only_waiting_visible_chats(script):
    module, _ = script
    out = run(module, "unread")
    assert "Andi — 2" in out
    assert "Baugruppe — 1" in out
    # Read, archived and hidden chats are not "waiting for you".
    assert "Gelesen" not in out
    assert "Archiviert" not in out
    assert "Versteckt" not in out


def test_full_shows_only_the_unread_incoming_ones(script):
    module, _ = script
    out = run(module, "unread", "--full")
    # Two unread means the last two incoming, oldest first — not the reply in
    # between, and not the older message that was already read.
    assert out.index("zweite") < out.index("dritte")
    assert "meine antwort" not in out
    assert "erste" not in out


def test_group_sender_comes_from_the_profile_name_not_pushname(script):
    module, _ = script
    out = run(module, "chat", "Baugruppe")
    assert "María" in out
    # ZWAMESSAGE.ZPUSHNAME holds a base64 blob in groups; using it leaks junk.
    assert "base64junk" not in out


def test_media_without_text_is_named_not_blank(script):
    module, _ = script
    assert "[Bild]" in run(module, "chat", "Baugruppe")


def test_group_system_events_are_left_out(script):
    module, _ = script
    assert "trat bei" not in run(module, "chat", "Baugruppe")


def test_ambiguous_name_asks_instead_of_guessing(script):
    module, _ = script
    with pytest.raises(SystemExit) as exit_info:
        run(module, "chat", "e")
    assert exit_info.value.code == 2


def test_reading_never_writes_to_the_store(script):
    module, store = script
    before = store.read_bytes()
    run(module, "unread", "--full")
    run(module, "chat", "Andi")
    # The whole design rests on this: summarising the morning must not mark
    # anything read, and must not be able to corrupt WhatsApp's own database.
    assert store.read_bytes() == before
    assert not (store.parent / "ChatStorage.sqlite-journal").exists()
