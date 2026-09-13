"""Stickers reach the model as a reaction, never as a picture.

The WhatsApp bridge saves a sticker as ``sticker_<hex>.webp`` and the gateway
hands that path to the model as an attached document. Now and then the model
opens it with ``vision_analyze`` and answers with a description of the sticker
("Süßer Katzen-Sticker mit ganz viel Liebe drumherum …") — in a stand-in, to a
real person, in the user's name. A rule in SOUL.md alone left that to chance,
so the picture is removed here, before the turn exists: what cannot be seen
cannot be described.

The same holds for a sticker that is only *quoted*: the adapter folds quoted
media into the event, so every ``sticker_`` path is dropped, not just the
direct one.
"""

from __future__ import annotations

import os

STICKER_TOKEN = "[Sticker]"
STICKER_NOTE = (
    "[Sticker — eine reine Reaktion ohne Inhalt. Nicht öffnen, nicht beschreiben, "
    "nicht deuten. Antworte höchstens so knapp, wie Marlon es selbst täte, "
    "oder gar nicht: NO_REPLY.]"
)


def _is_sticker_path(path) -> bool:
    return os.path.basename(str(path)).startswith("sticker_")


def _platform(event) -> str:
    platform = getattr(getattr(event, "source", None), "platform", None)
    return str(getattr(platform, "value", platform) or "")


def neutralise_stickers(event=None, **_):
    """``pre_gateway_dispatch``: strip sticker media and say what it was instead."""
    if event is None or _platform(event) != "whatsapp":
        return None

    urls = list(getattr(event, "media_urls", None) or [])
    types = list(getattr(event, "media_types", None) or [])
    keep = [i for i, url in enumerate(urls) if not _is_sticker_path(url)]
    dropped = len(keep) != len(urls)
    is_sticker = str(getattr(getattr(event, "message_type", None), "value", "")) == "sticker"
    text = getattr(event, "text", "") or ""

    if not (dropped or is_sticker or STICKER_TOKEN in text):
        return None

    # The runner rewrites text with dataclasses.replace(event, ...), which copies
    # the remaining fields from this same object — so media is cleared in place.
    event.media_urls = [urls[i] for i in keep]
    event.media_types = [types[i] for i in keep if i < len(types)]
    if is_sticker and not event.media_urls:
        from gateway.platforms.event import MessageType
        event.message_type = MessageType.TEXT

    if STICKER_TOKEN in text:
        text = text.replace(STICKER_TOKEN, STICKER_NOTE)
    elif is_sticker:
        text = f"{text} {STICKER_NOTE}".strip()
    return {"action": "rewrite", "text": text}


def register(ctx):
    ctx.register_hook("pre_gateway_dispatch", neutralise_stickers)
