#!/usr/bin/env python3
"""A Piper that stays warm, so speech starts in a breath rather than a beat.

The bridge used to spawn `piper` per sentence, and each spawn loads a 109 MB
ONNX model: about 1.2s before the first sample, every sentence, which is what
made a conversation feel like a telegram. Here the model is loaded once and
kept, so the same sentence starts in roughly a third of a second.

    POST /speech  {"text": "...", "model": "/path/to/voice.onnx"}
    -> raw little-endian int16 PCM at the model's own rate, streamed
       (X-Sample-Rate says which)

Loopback only, bearer token, and it holds at most a few models at a time —
a synthesiser that answers strangers or grows without limit is not an
improvement over a slow one.
"""
from __future__ import annotations

import json
import os
import sys
import threading
from collections import OrderedDict
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from piper import PiperVoice

VOICE_DIR = Path(os.environ.get("JARVIS_PIPER_VOICES",
                                Path.home() / ".hermes/piper-voices")).resolve()
MAX_LOADED = 3          # each model is ~100 MB resident
MAX_TEXT = 600

_voices: "OrderedDict[str, PiperVoice]" = OrderedDict()
_lock = threading.Lock()


def token() -> str:
    value = os.environ.get("JARVIS_APP_TOKEN", "")
    if value:
        return value
    try:
        for line in (Path.home() / ".hermes/.env").read_text().splitlines():
            name, _, raw = line.partition("=")
            if name.strip() == "JARVIS_APP_TOKEN" and raw.strip():
                return raw.strip().strip("'\"")
    except OSError:
        pass
    return ""


TOKEN = token()


def resolve(model: str) -> Path:
    """Only the voices directory. The request carries a filesystem path."""
    path = (Path(model) if model else VOICE_DIR / "de_DE-thorsten-high.onnx").resolve()
    if path.parent != VOICE_DIR or path.suffix != ".onnx" or not path.is_file():
        raise ValueError("Unbekannte Stimme")
    return path


def voice_for(path: Path) -> PiperVoice:
    key = str(path)
    with _lock:
        found = _voices.get(key)
        if found is not None:
            _voices.move_to_end(key)
            return found
    # Loading outside the lock: a cold model takes a second and must not stall
    # a request for a model that is already warm.
    loaded = PiperVoice.load(key)
    with _lock:
        _voices[key] = loaded
        _voices.move_to_end(key)
        while len(_voices) > MAX_LOADED:
            _voices.popitem(last=False)
        return _voices[key]


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):      # noqa: A003 - quiet by default
        pass

    def _json(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path != "/health":
            self._json(HTTPStatus.NOT_FOUND, {"error": "Nicht gefunden"})
            return
        with _lock:
            warm = list(_voices)
        self._json(HTTPStatus.OK, {"ok": True, "warm": [Path(v).stem for v in warm]})

    def do_POST(self):
        expected = f"Bearer {TOKEN}"
        if not TOKEN or self.headers.get("Authorization", "") != expected:
            self._json(HTTPStatus.UNAUTHORIZED, {"error": "Nicht autorisiert"})
            return
        if self.path != "/speech":
            self._json(HTTPStatus.NOT_FOUND, {"error": "Nicht gefunden"})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(min(length, 65536)) or b"{}")
            text = str(body.get("text") or "").strip()
            if not 1 <= len(text) <= MAX_TEXT:
                raise ValueError("Sprachtext muss 1 bis 600 Zeichen enthalten")
            path = resolve(str(body.get("model") or ""))
        except (ValueError, json.JSONDecodeError) as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return

        try:
            voice = voice_for(path)
        except Exception:
            self._json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "Stimme nicht ladbar"})
            return

        started = False
        try:
            for chunk in voice.synthesize(text):
                if not started:
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", "application/octet-stream")
                    self.send_header("X-Sample-Rate", str(chunk.sample_rate))
                    self.send_header("Connection", "close")
                    self.end_headers()
                    self.close_connection = True
                    started = True
                self.wfile.write(chunk.audio_int16_bytes)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            return                      # barge-in closed the stream; normal
        except Exception:
            if not started:
                self._json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "Synthese fehlgeschlagen"})
            return
        if not started:
            self._json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "Kein Audio"})


def main() -> int:
    port = int(os.environ.get("JARVIS_PIPER_PORT", "8789"))
    if not TOKEN:
        print("JARVIS_APP_TOKEN fehlt", file=sys.stderr)
        return 2
    # Preload the default voice so the very first sentence is fast too.
    try:
        voice_for(resolve(""))
    except Exception as exc:                      # noqa: BLE001
        print(f"Vorladen fehlgeschlagen: {exc}", file=sys.stderr)
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Piper warm auf 127.0.0.1:{port}, Stimmen aus {VOICE_DIR}", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
