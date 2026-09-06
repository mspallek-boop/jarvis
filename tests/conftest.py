"""Shared pytest fixtures + heavy-dependency stubs for the Jarvis test suite.

The voice server imports several heavyweight, hardware-bound packages
(``RealtimeSTT`` pulls in Whisper/torch, ``anthropic`` the cloud SDK, ``uvicorn``
the ASGI runner). None of them are needed to exercise the HTTP/WebSocket surface
or the pure security-relevant helpers, so we install lightweight stand-ins into
``sys.modules`` *before* importing ``server.py``. This keeps the tests fast,
deterministic and runnable on a machine with no GPU and no cloud keys.
"""

from __future__ import annotations

import importlib.util
import os
import socket
import sys
import types
from pathlib import Path
from unittest import mock

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SERVER_PY = REPO_ROOT / "server" / "server.py"


# --------------------------------------------------------------------------- #
# Stub the heavy imports before loading server.py                              #
# --------------------------------------------------------------------------- #
def _install_stubs() -> None:
    if "RealtimeSTT" not in sys.modules:
        rt = types.ModuleType("RealtimeSTT")

        class _Recorder:  # minimal stand-in for AudioToTextRecorder
            def __init__(self, *a, **k):
                self._args = a
                self._kwargs = k

            def feed_audio(self, *a, **k):
                return None

            def perform_final_transcription(self, *a, **k):
                return ""

            def clear_audio_queue(self, *a, **k):
                return None

        rt.AudioToTextRecorder = _Recorder
        sys.modules["RealtimeSTT"] = rt

    if "anthropic" not in sys.modules:
        an = types.ModuleType("anthropic")

        class _Anthropic:
            def __init__(self, *a, **k):
                pass

        an.Anthropic = _Anthropic
        sys.modules["anthropic"] = an

    if "uvicorn" not in sys.modules:
        uv = types.ModuleType("uvicorn")
        uv.Server = object
        uv.Config = object
        uv.run = lambda *a, **k: None
        sys.modules["uvicorn"] = uv


@pytest.fixture(scope="session")
def network_guard():
    """Block real IP traffic (including localhost) and DNS, not ASGI/socketpair.

    Record attempts too: a production handler may catch the raised exception;
    the test must still fail if it forgot to stub a backend.
    """
    attempts = []

    def blocked(*args, **kwargs):
        attempts.append("unstubbed network operation")
        raise AssertionError("Offline test attempted network access; stub the backend")

    def guard_ip(original):
        def guarded(sock, *args, **kwargs):
            if sock.family in (socket.AF_INET, socket.AF_INET6):
                return blocked()
            return original(sock, *args, **kwargs)
        return guarded

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(socket, "getaddrinfo", blocked)
        patch.setattr(socket, "gethostbyname", blocked)
        patch.setattr(socket, "gethostbyname_ex", blocked)
        patch.setattr(socket, "gethostbyaddr", blocked)
        for name in ("connect", "connect_ex", "sendto", "sendall", "send"):
            patch.setattr(socket.socket, name, guard_ip(getattr(socket.socket, name)))
        yield attempts
    assert not attempts, "Suite attempted real network access"


@pytest.fixture(autouse=True)
def offline_network(network_guard):
    before = len(network_guard)
    yield
    assert len(network_guard) == before, "Test attempted real network access"


@pytest.fixture(scope="session")
def server_mod(network_guard):
    """Import server.py exactly once with heavy deps stubbed out."""
    _install_stubs()
    spec = importlib.util.spec_from_file_location("jarvis_server", SERVER_PY)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["jarvis_server"] = mod
    # The production loader reads ~/.hermes/.env at import time. Tests must not
    # inherit credentials or local service configuration from either env file.
    env_paths = {Path.home() / ".hermes" / ".env", SERVER_PY.parent / ".env"}
    exists = Path.exists
    with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(
        Path, "exists", lambda path: False if path in env_paths else exists(path)
    ):
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


@pytest.fixture(autouse=True)
def isolated_server_files(server_mod, monkeypatch, tmp_path):
    """Keep test usage/session/latency state independent of real local files."""
    for name in ("LOG_PATH", "STATE_PATH", "USAGE_PATH", "FIRED_PATH"):
        monkeypatch.setattr(server_mod, name, tmp_path / (name.lower() + ".json"))


@pytest.fixture()
def no_token(monkeypatch, server_mod):
    """Default deployment posture: JARVIS_HUD_TOKEN unset -> auth disabled."""
    monkeypatch.delenv("JARVIS_HUD_TOKEN", raising=False)
    return server_mod


@pytest.fixture()
def with_token(monkeypatch, server_mod):
    """Hardened posture: a HUD token is configured."""
    monkeypatch.setenv("JARVIS_HUD_TOKEN", "s3cr3t-token")
    return server_mod


@pytest.fixture(autouse=True)
def _clean_ws_clients(server_mod):
    """WS_CLIENTS is a module global; isolate it so a leaked fake HUD from one
    test can't inflate another's broadcast count."""
    server_mod.WS_CLIENTS.clear()
    yield
    server_mod.WS_CLIENTS.clear()


@pytest.fixture()
def client(server_mod):
    """TestClient for the main voice/HUD app (no lifespan -> no STT warm)."""
    from fastapi.testclient import TestClient

    return TestClient(server_mod.app)


@pytest.fixture()
def dash_client(server_mod):
    """TestClient for the dashboard TLS reverse-proxy app."""
    from fastapi.testclient import TestClient

    return TestClient(server_mod.dash_app)
