#!/usr/bin/env python3
"""Read WhatsApp — unread chats and their messages — from WhatsApp Desktop.

    jarvis-whatsapp-read.py unread              # which chats are waiting
    jarvis-whatsapp-read.py unread --full       # and what they actually say
    jarvis-whatsapp-read.py chat Andi           # the last messages of one chat

Why not the Baileys bridge: it keeps no message store at all
(`syncFullHistory: false`, and its queue is *drained* by whoever reads it), and
in self-chat mode it discards other people's messages before anything sees
them. Asking it for "the unread ones" cannot work — there is nothing to ask.

WhatsApp Desktop, meanwhile, keeps every chat in a plain unencrypted SQLite
file inside its group container, updated live. So this reads that, and nothing
in this file ever writes: the connection is opened `mode=ro` and the code has
no INSERT, UPDATE or DELETE. Reading leaves the chats unread in WhatsApp, which
is the point — JARVIS summarising your morning must not silently mark it read.

`mode=ro` rather than `immutable=1`: the immutable flag ignores the -wal file,
and the newest hours of messages live exactly there. Measured on this Mac, the
immutable view was two and a half hours behind.
"""

import argparse
import os
import sqlite3
import sys
from datetime import datetime, timedelta

STORE = os.environ.get("JARVIS_WA_STORE") or os.path.expanduser(
    "~/Library/Group Containers/group.net.whatsapp.WhatsApp.shared/ChatStorage.sqlite"
)

# Core Data counts seconds from 2001-01-01, unix time from 1970-01-01.
COCOA_EPOCH = 978307200

# WhatsApp stores no text for anything that is not text. Naming the kind beats
# printing an empty line, and beats guessing at content that is not in the row.
KINDS = {
    1: "[Bild]", 2: "[Sprachnachricht]", 3: "[Video]", 4: "[Kontakt]",
    5: "[Standort]", 7: "[Link]", 8: "[Dokument]", 11: "[GIF]",
    14: "[gelöscht]", 15: "[Sticker]", 46: "[Umfrage]",
}


def connect():
    if not os.path.exists(STORE):
        sys.exit("WhatsApp Desktop ist auf diesem Mac nicht eingerichtet.")
    try:
        return sqlite3.connect(f"file:{STORE}?mode=ro", uri=True, timeout=5)
    except sqlite3.OperationalError as exc:
        sys.exit(f"WhatsApp-Datenbank nicht lesbar: {exc}")


def when(stamp):
    """Absolute date, or a clock time for today — a summary read out loud wants
    'um 16:09', not a full ISO timestamp."""
    if not stamp:
        return "?"
    try:
        moment = datetime.fromtimestamp(stamp + COCOA_EPOCH)
    except (ValueError, OSError, OverflowError):
        return "?"
    # Pinned and drafted chats can carry timestamps decades in the future.
    if moment > datetime.now() + timedelta(days=1):
        return "?"
    today = datetime.now().date()
    if moment.date() == today:
        return moment.strftime("%H:%M")
    if moment.date() == today - timedelta(days=1):
        return moment.strftime("gestern %H:%M")
    return moment.strftime("%d.%m. %H:%M")


def body(text, kind):
    text = (text or "").strip().replace("\n", " ")
    label = KINDS.get(kind)
    if text and label:
        return f"{label} {text}"
    if text:
        return text
    return label or f"[Nachricht Typ {kind}]"


def chats_with_unread(db):
    return db.execute("""
        SELECT Z_PK, ZPARTNERNAME, ZUNREADCOUNT, ZLASTMESSAGEDATE
        FROM ZWACHATSESSION
        WHERE ZUNREADCOUNT > 0 AND ZHIDDEN = 0 AND ZARCHIVED = 0
        ORDER BY ZLASTMESSAGEDATE DESC
    """).fetchall()


def messages(db, chat_pk, limit, incoming_only=False):
    """Newest `limit` messages of one chat, returned oldest-first so a
    conversation reads in the order it happened."""
    # Who wrote it, in descending order of how much the user would recognise
    # the name: their own address-book entry, then the name the sender chose
    # for themselves, then the bare number.
    #
    # `ZWAMESSAGE.ZPUSHNAME` looks like the obvious source and is a trap — in
    # group chats it holds a base64 blob, not a name. The names live in
    # `ZWAPROFILEPUSHNAME`, keyed by the member's JID, which for newer accounts
    # is a `@lid` privacy identifier rather than a phone number.
    rows = db.execute(f"""
        SELECT m.ZTEXT, m.ZMESSAGETYPE, m.ZMESSAGEDATE, m.ZISFROMME,
               COALESCE(NULLIF(g.ZCONTACTNAME, ''), NULLIF(g.ZFIRSTNAME, ''),
                        p.ZPUSHNAME, substr(g.ZMEMBERJID, 1, instr(g.ZMEMBERJID, '@') - 1))
        FROM ZWAMESSAGE m
        LEFT JOIN ZWAGROUPMEMBER g ON g.Z_PK = m.ZGROUPMEMBER
        LEFT JOIN ZWAPROFILEPUSHNAME p ON p.ZJID = g.ZMEMBERJID
        WHERE m.ZCHATSESSION = ?
          {"AND m.ZISFROMME = 0" if incoming_only else ""}
          AND m.ZMESSAGETYPE != 6
        ORDER BY m.ZMESSAGEDATE DESC
        LIMIT ?
    """, (chat_pk, limit)).fetchall()
    return list(reversed(rows))


def render(rows, group):
    for text, kind, stamp, from_me, sender in rows:
        if from_me:
            who = "du"
        elif group:
            who = sender or "jemand"
        else:
            who = ""
        prefix = f"{who}: " if who else ""
        print(f"  {when(stamp)}  {prefix}{body(text, kind)}")


def is_group(db, chat_pk):
    row = db.execute(
        "SELECT ZGROUPINFO FROM ZWACHATSESSION WHERE Z_PK = ?", (chat_pk,)
    ).fetchone()
    return bool(row and row[0])


def cmd_unread(db, args):
    rows = chats_with_unread(db)
    if not rows:
        print("Keine ungelesenen Nachrichten.")
        return
    total = sum(r[2] for r in rows)
    print(f"{len(rows)} Chats, {total} ungelesene Nachrichten:\n")
    for pk, name, count, stamp in rows:
        print(f"{name or '?'} — {count}, zuletzt {when(stamp)}")
        if args.full:
            # The unread ones are the last `count` incoming messages. Capped,
            # because a chat with 172 waiting is not a summary, it is a wall.
            render(messages(db, pk, min(count, args.limit), incoming_only=True),
                   is_group(db, pk))
            if count > args.limit:
                print(f"  … {count - args.limit} weitere ungelesene")
            print()


def cmd_chat(db, args):
    query = " ".join(args.name)
    rows = db.execute("""
        SELECT Z_PK, ZPARTNERNAME, ZUNREADCOUNT FROM ZWACHATSESSION
        WHERE ZPARTNERNAME LIKE ? AND ZHIDDEN = 0
        ORDER BY ZLASTMESSAGEDATE DESC LIMIT 6
    """, (f"%{query}%",)).fetchall()

    if not rows:
        sys.exit(f"Kein Chat gefunden für: {query}")
    if len(rows) > 1:
        # Answering the wrong chat is worse than asking. Same rule as
        # jarvis-home.sh.
        print("Mehrdeutig — welcher?", file=sys.stderr)
        for _, name, count in rows:
            waiting = f" ({count} ungelesen)" if count else ""
            print(f"  {name}{waiting}", file=sys.stderr)
        sys.exit(2)

    pk, name, count = rows[0]
    waiting = f", {count} ungelesen" if count else ""
    print(f"{name}{waiting}:\n")
    render(messages(db, pk, args.limit), is_group(db, pk))


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    subs = parser.add_subparsers(dest="command", required=True)

    unread = subs.add_parser("unread", help="Chats mit ungelesenen Nachrichten")
    unread.add_argument("--full", action="store_true",
                        help="auch den Text der ungelesenen Nachrichten")
    unread.add_argument("--limit", type=int, default=15,
                        help="höchstens so viele je Chat (Vorgabe 15)")
    unread.set_defaults(func=cmd_unread)

    chat = subs.add_parser("chat", help="die letzten Nachrichten eines Chats")
    chat.add_argument("name", nargs="+")
    chat.add_argument("--limit", type=int, default=25)
    chat.set_defaults(func=cmd_chat)

    args = parser.parse_args()
    db = connect()
    try:
        args.func(db, args)
    finally:
        db.close()


if __name__ == "__main__":
    main()
