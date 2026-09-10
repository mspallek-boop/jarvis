"""An upload is a body too, and the two limits disagreed.

`MAX_UPLOAD_BYTES` welcomed ten megabytes while `_body` refused anything past
sixty-four kilobytes, and `_body` runs first. Every pasted image — every image
is larger than 64 KB — came back "Ungültige Anfragegröße", so no picture ever
reached JARVIS from either app.
"""
import base64
import importlib.util
import io
import json
from pathlib import Path
import sys

import pytest

spec = importlib.util.spec_from_file_location(
    "upload_limit_bridge", Path(__file__).resolve().parents[1] / "bridge/jarvis_bridge.py")
bridge = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = bridge
spec.loader.exec_module(bridge)


class Reader:
    """Just enough of the handler for `_body` to run against."""

    def __init__(self, payload: bytes, path: str):
        self.headers = {"Content-Length": str(len(payload))}
        self.rfile = io.BytesIO(payload)
        self.path = path

    _body = bridge.JarvisHandler._body


def payload_of(size: int) -> bytes:
    return json.dumps({"data": base64.b64encode(b"\x00" * size).decode()}).encode()


def test_a_photograph_sized_upload_is_accepted():
    """1.7 MB is an ordinary screenshot, and it used to be refused outright."""
    body = payload_of(1_705_755)
    assert len(body) > bridge.MAX_BODY_BYTES          # the old ceiling
    parsed = Reader(body, "/upload")._body(limit=bridge.MAX_UPLOAD_BODY_BYTES)
    assert parsed["data"]


def test_the_upload_ceiling_still_has_a_ceiling():
    """Raised, not removed: a body past the upload limit is still refused."""
    oversized = b"x" * (bridge.MAX_UPLOAD_BODY_BYTES + 1)
    with pytest.raises(ValueError, match="Anfragegröße"):
        Reader(oversized, "/upload")._body(limit=bridge.MAX_UPLOAD_BODY_BYTES)


def test_ordinary_routes_keep_the_small_ceiling():
    """Only uploads get the room. A chat message has no business being 10 MB."""
    body = payload_of(200_000)
    with pytest.raises(ValueError, match="Anfragegröße"):
        Reader(body, "/chat")._body()


def test_the_upload_ceiling_covers_base64_overhead():
    """Encoding costs a third; a limit that ignored it would refuse a legal
    upload for being the size base64 made it."""
    assert bridge.MAX_UPLOAD_BODY_BYTES > bridge.MAX_UPLOAD_BYTES * 4 // 3
