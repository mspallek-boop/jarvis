"""TTS fallback: whatever ElevenLabs refuses, JARVIS still speaks.

Silence is the one outcome the user actually notices. A cloud voice that says
no — an exhausted quota, a plan limit, a voice id that was never filled in, a
dropped connection — must hand the sentence to the local macOS voice instead
of failing the turn on both devices.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def pipeline(monkeypatch, tmp_path):
    """The real VoicePipelineServer with only its outside world stubbed."""
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    monkeypatch.setenv("ELEVENLABS_VOICE_ID", "voice-from-the-env")
    spec = importlib.util.spec_from_file_location("jarvis_server", ROOT / "server" / "server.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["jarvis_server"] = module
    spec.loader.exec_module(module)

    server = module.VoicePipelineServer.__new__(module.VoicePipelineServer)
    server.cfg = {"voice": {"provider": "elevenlabs", "fallback": "macos",
                            "macos_voice": "", "model": "eleven_flash_v2_5",
                            "voice_id": "YOUR_ELEVENLABS_VOICE_ID",
                            "output_format": "pcm_16000"}}
    spoken: list = []
    monkeypatch.setattr(module, "shutil", type("S", (), {"which": staticmethod(lambda _c: "/usr/bin/say")}))
    monkeypatch.setattr(module, "record_usage", lambda **_k: None)
    server._macos_tts_chunks = lambda text, timing: (spoken.append(text), iter([b"\x01\x02"]))[1]
    return module, server, spoken


def timing(module):
    return module.TurnTiming(turn_id=1)


def refuse(module, monkeypatch, status: int, body: str = "nope"):
    class Response:
        status_code = status
        text = body

        def close(self):
            pass

    monkeypatch.setattr(module.requests, "post", lambda *a, **k: Response())


@pytest.mark.parametrize("status", [400, 401, 402, 404, 429, 500, 503])
def test_any_refusal_still_speaks(pipeline, monkeypatch, status):
    """Not a list of blessed status codes.

    404 is the one that bit: a placeholder voice_id in server.yaml answers
    `voice_not_found`, which fell past a fallback that only named 401/402/429,
    and the turn died silently on Mac and iPhone alike.
    """
    module, server, spoken = pipeline
    refuse(module, monkeypatch, status)
    chunks = list(server.tts_chunks_sync("Guten Abend", timing(module)))
    assert chunks == [b"\x01\x02"]
    assert spoken == ["Guten Abend"]


def test_an_unreachable_service_still_speaks(pipeline, monkeypatch):
    """A dropped connection sounds exactly like a refused one: nothing said."""
    module, server, spoken = pipeline

    def boom(*_a, **_k):
        raise module.requests.RequestException("connection reset")

    monkeypatch.setattr(module.requests, "post", boom)
    assert list(server.tts_chunks_sync("Hallo", timing(module))) == [b"\x01\x02"]
    assert spoken == ["Hallo"]


def test_without_a_local_voice_the_error_still_surfaces(pipeline, monkeypatch):
    """Falling back is not the same as swallowing: no `say`, no pretending."""
    module, server, _ = pipeline
    monkeypatch.setattr(module, "shutil", type("S", (), {"which": staticmethod(lambda _c: None)}))
    refuse(module, monkeypatch, 404, "voice_not_found")
    with pytest.raises(RuntimeError, match="404"):
        list(server.tts_chunks_sync("Hallo", timing(module)))


def test_the_env_voice_beats_a_placeholder_in_the_file(pipeline, monkeypatch):
    """server.yaml is copied from the example; ~/.hermes/.env is kept current."""
    module, server, _ = pipeline
    seen: dict = {}

    class Response:
        status_code = 200

        def iter_content(self, chunk_size=4096):
            return iter([b"\xaa"])

        def close(self):
            pass

    def capture(url, **kwargs):
        seen["url"] = url
        return Response()

    monkeypatch.setattr(module.requests, "post", capture)
    list(server.tts_chunks_sync("Hallo", timing(module)))
    assert "voice-from-the-env" in seen["url"]
    assert "YOUR_ELEVENLABS_VOICE_ID" not in seen["url"]


def test_a_real_file_voice_is_not_overridden_by_a_placeholder_env(pipeline, monkeypatch):
    """The env only wins when it actually holds a voice."""
    module, server, _ = pipeline
    monkeypatch.setenv("ELEVENLABS_VOICE_ID", "YOUR_ELEVENLABS_VOICE_ID")
    server.cfg["voice"]["voice_id"] = "a-real-voice"
    seen: dict = {}

    class Response:
        status_code = 200

        def iter_content(self, chunk_size=4096):
            return iter([b"\xaa"])

        def close(self):
            pass

    monkeypatch.setattr(module.requests, "post", lambda url, **k: (seen.update(url=url), Response())[1])
    list(server.tts_chunks_sync("Hallo", timing(module)))
    assert "a-real-voice" in seen["url"]
