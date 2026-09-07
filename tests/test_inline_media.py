"""Offline coverage of Hermes SSE -> bridge JSON/NDJSON -> raster attachment."""
import base64
import importlib.util
import io
import json
import os
from pathlib import Path
import struct
import sys
from types import SimpleNamespace
from unittest.mock import Mock
import zlib

import pytest

spec = importlib.util.spec_from_file_location(
    "inline_media_bridge", Path(__file__).resolve().parents[1] / "bridge/jarvis_bridge.py")
bridge = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = bridge
spec.loader.exec_module(bridge)


def png():
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00")) + chunk(b"IEND", b""))


def data_url(data=None, mime="image/png"):
    return f"data:{mime};base64,{base64.b64encode(png() if data is None else data).decode()}"


@pytest.fixture
def media_dir(tmp_path, monkeypatch):
    root = tmp_path / "jarvis-media"
    root.mkdir()
    monkeypatch.setattr(bridge, "LOCAL_MEDIA_ROOT", root)
    return root


def test_actual_api_markdown_is_extracted_without_base64_in_text():
    url = data_url()
    text, attachments = bridge.prepare_answer_media(f"Knoblauch: ![image]({url})")
    assert text == "Knoblauch: [Bild]"
    assert attachments == [{"kind": "image", "url": url, "title": "image"}]


def test_local_reference_and_spaces(media_dir):
    path = media_dir / "mein knoblauch.png"
    path.write_bytes(png())
    text, attachments = bridge.prepare_answer_media(f'MEDIA:"{path}"')
    assert "MEDIA:" not in text
    assert base64.b64decode(attachments[0]["url"].split(",")[1]) == png()


@pytest.mark.parametrize("path", ["../outside.png", "sub/../../outside.png", ".hidden.png", "sub//pic.png"])
def test_traversal_and_hidden_paths_rejected(media_dir, path):
    (media_dir.parent / "outside.png").write_bytes(png())
    with pytest.raises(ValueError):
        bridge._read_local_image(f"{media_dir}/{path}")


def test_external_files_and_prefix_collision_are_rejected(media_dir):
    for path in ["/etc/passwd", str(media_dir) + "-other/pic.png", "file:///tmp/pic.png"]:
        with pytest.raises(ValueError):
            bridge._read_local_image(path)


def test_symlink_file_directory_and_root_rejected(media_dir):
    outside = media_dir.parent / "outside"
    outside.mkdir()
    (outside / "pic.png").write_bytes(png())
    (media_dir / "link.png").symlink_to(outside / "pic.png")
    (media_dir / "sub").symlink_to(outside, target_is_directory=True)
    for path in [media_dir / "link.png", media_dir / "sub/pic.png"]:
        with pytest.raises(OSError):
            bridge._read_local_image(str(path))
    media_dir.rename(media_dir.with_name("moved"))
    media_dir.symlink_to(outside, target_is_directory=True)
    with pytest.raises(OSError):
        bridge._read_local_image(str(media_dir / "pic.png"))


def test_hardlink_fifo_directory_and_oversize_rejected(media_dir, monkeypatch):
    original = media_dir.parent / "original.png"
    original.write_bytes(png())
    os.link(original, media_dir / "hard.png")
    os.mkfifo(media_dir / "pipe.png")
    (media_dir / "folder.png").mkdir()
    (media_dir / "large.png").write_bytes(png() + b"x")
    monkeypatch.setattr(bridge, "MAX_INLINE_IMAGE_BYTES", len(png()))
    for name in ["hard.png", "pipe.png", "folder.png", "large.png"]:
        with pytest.raises((OSError, ValueError)):
            bridge._read_local_image(str(media_dir / name))


@pytest.mark.parametrize("url", [
    "data:image/png;base64,%%%", "data:image/svg+xml;base64,PHN2Zy8+",
    data_url(b"<html>script</html>"), data_url(mime="image/jpeg"),
    "data:text/html;base64,PHNjcmlwdD4=", "data:image/png;base64,",
])
def test_invalid_data_and_mime_mismatch_leave_visible_failure(url):
    text, attachments = bridge.prepare_answer_media(f"![bad]({url})")
    assert text == "[Bild nicht verfügbar]" and attachments == []


def test_missing_and_fake_local_images_leave_visible_failure(media_dir):
    fake = media_dir / "fake.png"
    fake.write_text("<svg/>")
    for path in [fake, media_dir / "missing.png"]:
        text, attachments = bridge.prepare_answer_media(f"MEDIA:{path}")
        assert text == "[Bild nicht verfügbar]" and attachments == []


def test_size_total_count_and_deduplication(monkeypatch):
    url = data_url()
    other = data_url(png() + b"x")
    text, attachments = bridge.prepare_answer_media(f"![a]({url}) ![b]({url})")
    assert len(attachments) == 1
    monkeypatch.setattr(bridge, "MAX_INLINE_TOTAL_BYTES", len(png()))
    text, attachments = bridge.prepare_answer_media(f"![a]({url}) ![b]({other})")
    assert len(attachments) == 1 and "nicht verfügbar" in text
    monkeypatch.setattr(bridge, "MAX_INLINE_IMAGE_BYTES", len(png()) - 1)
    assert bridge.prepare_answer_media(f"![a]({url})")[1] == []


@pytest.mark.parametrize("route", ["/chat", "/chat/stream"])
@pytest.mark.parametrize("local", [False, True])
def test_real_sse_to_http_response(route, local, media_dir, monkeypatch):
    path = media_dir / "knoblauch.png"
    path.write_bytes(png())
    reference = f"MEDIA:{path}" if local else f"![image]({data_url()})"
    events = [("assistant.delta", {"delta": f"MEDIA:{path}"}),
              ("assistant.completed", {"content": reference})]
    stream = io.BytesIO(b"".join(
        f"event: {name}\ndata: {json.dumps(data)}\n\n".encode() for name, data in events))
    monkeypatch.setattr(bridge.urllib.request, "urlopen", Mock(return_value=stream))
    config = SimpleNamespace(hermes_url="http://offline.invalid", app_token="test-only")
    client = bridge.HermesClient(config)
    client._session_id = lambda *args, **kwargs: "session"
    client._headers = lambda *args: {}
    body = json.dumps({"message": "Bild", "conversation": "test", "client_run_id": "test"}).encode()
    handler = bridge.JarvisHandler.__new__(bridge.JarvisHandler)
    handler.config, handler.client = config, client
    handler.rfile = io.BytesIO((f"POST {route} HTTP/1.1\r\nHost: localhost\r\n"
                               f"Authorization: Bearer test-only\r\nContent-Length: {len(body)}\r\n\r\n").encode() + body)
    handler.wfile = io.BytesIO()
    handler.client_address = ("127.0.0.1", 1)
    handler.log_message = lambda *args: None
    handler.handle_one_request()
    headers, body = handler.wfile.getvalue().split(b"\r\n\r\n", 1)
    assert headers.startswith(b"HTTP/1.0 200")
    if route.endswith("stream"):
        frames = [json.loads(line) for line in body.splitlines()]
        result = frames[-1]["response"]
        assert all("MEDIA:" not in f.get("text", "") and "base64" not in f.get("text", "") for f in frames)
    else:
        result = json.loads(body)
    assert result["text"] == "[Bild]"
    assert result["attachments"][0]["url"] == data_url()
