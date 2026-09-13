"""The sticker hook: a WhatsApp sticker reaches the model as a note, never as a picture.

Hermes is not installed in the test venv, so the event is a stand-in dataclass
with the same fields and ``gateway.platforms.event`` is a tiny fake module.
"""

from __future__ import annotations

import dataclasses
import enum
import importlib
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "hermes-plugin"))


class MessageType(enum.Enum):
    TEXT = "text"
    PHOTO = "photo"
    STICKER = "sticker"


@dataclasses.dataclass
class Event:
    text: str
    message_type: MessageType = MessageType.TEXT
    source: object = None
    media_urls: list = dataclasses.field(default_factory=list)
    media_types: list = dataclasses.field(default_factory=list)


@pytest.fixture(scope="module")
def hook():
    fake = types.ModuleType("gateway.platforms.event")
    fake.MessageType = MessageType
    sys.modules.setdefault("gateway", types.ModuleType("gateway"))
    sys.modules.setdefault("gateway.platforms", types.ModuleType("gateway.platforms"))
    sys.modules["gateway.platforms.event"] = fake
    return importlib.import_module("jarvis_whatsapp_sticker")


def whatsapp():
    return SimpleNamespace(platform=SimpleNamespace(value="whatsapp"))


STICKER = "/Users/x/.hermes/image_cache/sticker_d8c19be15c07.webp"


def dispatch(hook, event):
    """What the gateway runner does with a rewrite result."""
    result = hook.neutralise_stickers(event=event, gateway=None, session_store=None)
    if result and result.get("action") == "rewrite":
        return dataclasses.replace(event, text=result["text"])
    return event


def test_a_sticker_loses_its_picture_and_becomes_a_note(hook):
    event = Event("[Sticker]", MessageType.STICKER, whatsapp(), [STICKER], ["unknown"])
    out = dispatch(hook, event)
    assert out.media_urls == [] and out.media_types == []
    assert out.message_type is MessageType.TEXT
    assert "[Sticker]" not in out.text
    assert "nicht beschreiben" in out.text and "NO_REPLY" in out.text


def test_the_owner_marker_survives_so_a_takeover_still_ends_the_standin(hook):
    event = Event("[owner reply] [Sticker]", MessageType.STICKER, whatsapp(), [STICKER], ["unknown"])
    out = dispatch(hook, event)
    assert out.text.startswith("[owner reply] ")
    assert out.media_urls == []


def test_a_quoted_sticker_is_dropped_but_a_real_photo_stays(hook):
    photo = "/Users/x/.hermes/image_cache/img_abc.jpg"
    event = Event("was ist das?", MessageType.PHOTO, whatsapp(),
                  [photo, STICKER], ["image/jpeg", "image/webp"])
    out = dispatch(hook, event)
    assert out.media_urls == [photo] and out.media_types == ["image/jpeg"]
    assert out.message_type is MessageType.PHOTO
    assert out.text == "was ist das?"


@pytest.mark.parametrize("event", [
    Event("Hallo", MessageType.TEXT, SimpleNamespace(platform=SimpleNamespace(value="whatsapp"))),
    Event("[Sticker]", MessageType.STICKER,
          SimpleNamespace(platform=SimpleNamespace(value="telegram")), [STICKER], ["unknown"]),
])
def test_everything_else_is_left_alone(hook, event):
    assert hook.neutralise_stickers(event=event) is None
