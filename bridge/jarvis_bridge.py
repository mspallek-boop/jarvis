#!/usr/bin/env python3
"""Small authenticated bridge between the native JARVIS app and Hermes Agent.

It deliberately uses only Python's standard library. Hermes' powerful API key
never leaves the Mac; clients only receive a separate JARVIS app token.
"""

from __future__ import annotations

import argparse
import base64
import hmac
import json
import re
import os
import secrets
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Iterator
from urllib.parse import urlparse
from urllib.parse import parse_qs, quote, unquote


WEEKDAYS_DE = ("Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag",
               "Samstag", "Sonntag")
MONTHS_DE = ("Januar", "Februar", "März", "April", "Mai", "Juni", "Juli",
             "August", "September", "Oktober", "November", "Dezember")


def _now_context() -> str:
    """The model has no clock and will invent a weekday if none is given.

    It guessed "Mittwoch" and "the day has just begun" at 18:12 on a Sunday.
    Every turn therefore carries the real local time as a marked context line.
    """
    now = datetime.now().astimezone()
    return (f"[Kontext: {WEEKDAYS_DE[now.weekday()]}, {now.day}. "
            f"{MONTHS_DE[now.month - 1]} {now.year}, {now:%H:%M} Uhr]")


DEFAULT_ENV = Path.home() / ".hermes" / ".env"
DEFAULT_STATE = Path.home() / ".hermes" / "jarvis-app-sessions.json"
# A session id is interpolated into /api/sessions/{id}/chat/stream, so it must
# never carry a slash, dot-segment, or query character.
SESSION_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}")
# A run id is interpolated into /v1/runs/{id}/stop, so it needs the same care.
RUN_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}")
# Client-chosen correlation id. A shared conversation is served by several
# clients at once, so "cancel the conversation" is ambiguous and can stop
# another surface's turn. A caller may only ever cancel its own run.
CLIENT_RUN_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}")
MAX_BODY_BYTES = 64 * 1024
# The gateway applies `limit` to a SUBSTRING search and only then filters for
# an exact title, so the wanted row can sit behind newer near-matches. Page
# through a bounded number of them rather than trusting one request.
LOOKUP_PAGE = 200
LOOKUP_MAX_PAGES = 5
BLOCKED_PATH_PARTS = {".ssh", ".gnupg", ".hermes", "Keychains"}
BLOCKED_FILE_SUFFIXES = {".key", ".pem", ".p12", ".pfx"}


def load_env(path: Path = DEFAULT_ENV) -> None:
    """Load missing values from Hermes' env file without overwriting the shell."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"").strip("'")
        if key:
            os.environ.setdefault(key, value)


def constant_time_token_matches(expected: str, supplied: str) -> bool:
    return bool(expected and supplied and hmac.compare_digest(expected, supplied))


def parse_sse(lines: Iterator[bytes]) -> Iterator[tuple[str, dict]]:
    """Parse Hermes' event stream into event/data pairs."""
    event_name = ""
    for raw in lines:
        line = raw.decode("utf-8", errors="replace").strip()
        if line.startswith("event:"):
            event_name = line[6:].strip()
        elif line.startswith("data:"):
            try:
                data = json.loads(line[5:].strip())
            except json.JSONDecodeError:
                continue
            if not isinstance(data, dict):
                # A bare JSON list/string/number is valid JSON but has no
                # .get(); without this guard it raised AttributeError and
                # killed the whole stream mid-turn.
                continue
            yield event_name or str(data.get("event", "")), data
            event_name = ""


@dataclass(frozen=True)
class BridgeConfig:
    host: str
    port: int
    hermes_url: str
    hermes_key: str
    app_token: str
    speech_provider: str = "local"
    elevenlabs_key: str = field(default="", repr=False)
    elevenlabs_voice_id: str = ""
    elevenlabs_model: str = "eleven_multilingual_v2"
    elevenlabs_stability: float = 0.6
    elevenlabs_similarity: float = 0.8
    elevenlabs_style: float = 0.0
    relay_url: str = ""
    session_key: str = "jarvis:user:apple"
    state_path: Path = DEFAULT_STATE
    file_roots: tuple[Path, ...] = (Path.home(),)

    @classmethod
    def from_environment(cls, host: str, port: int) -> "BridgeConfig":
        load_env()
        hermes_key = os.environ.get("API_SERVER_KEY", "").strip()
        app_token = (
            os.environ.get("JARVIS_APP_TOKEN", "").strip()
            or os.environ.get("JARVIS_HUD_TOKEN", "").strip()
        )
        if not hermes_key:
            raise SystemExit("API_SERVER_KEY is missing in ~/.hermes/.env")
        if not app_token:
            raise SystemExit("JARVIS_APP_TOKEN is missing in ~/.hermes/.env")
        if host not in {"127.0.0.1", "localhost", "::1"} and len(app_token) < 24:
            raise SystemExit("JARVIS_APP_TOKEN must be at least 24 characters for network access")
        roots_value = os.environ.get("JARVIS_FILE_ROOTS", str(Path.home()))
        roots = tuple(Path(value).expanduser().resolve() for value in roots_value.split(os.pathsep) if value.strip())
        return cls(
            host=host,
            port=port,
            hermes_url=os.environ.get("HERMES_API_URL", "http://127.0.0.1:8642").rstrip("/"),
            hermes_key=hermes_key,
            app_token=app_token,
            session_key=os.environ.get("JARVIS_SESSION_KEY", "jarvis:user:apple"),
            file_roots=roots or (Path.home().resolve(),),
            relay_url=os.environ.get("JARVIS_RELAY_URL", "").strip(),
            speech_provider=os.environ.get("JARVIS_TTS_PROVIDER", "local").strip(),
            elevenlabs_key=os.environ.get("ELEVENLABS_API_KEY", "").strip(),
            elevenlabs_voice_id=os.environ.get("ELEVENLABS_VOICE_ID", "").strip(),
            elevenlabs_model=os.environ.get("ELEVENLABS_MODEL", "eleven_multilingual_v2").strip(),
            elevenlabs_stability=_env_float("ELEVENLABS_STABILITY", 0.6),
            elevenlabs_similarity=_env_float("ELEVENLABS_SIMILARITY", 0.8),
            elevenlabs_style=_env_float("ELEVENLABS_STYLE", 0.0),
        )


def _env_float(name: str, default: float) -> float:
    """A malformed value must not take the whole bridge down at startup."""
    try:
        return min(1.0, max(0.0, float(os.environ.get(name, "").strip())))
    except ValueError:
        return default


# Only the turbo/flash models accept language_code; multilingual_v2 rejects
# the field with HTTP 400, so it is sent selectively.
LANGUAGE_CODE_MODELS = ("eleven_flash_v2_5", "eleven_turbo_v2_5")


class _NoSpeechRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _open_neural_speech(text: str, token: str):
    """Fixed loopback worker; no proxies, redirects, or Hermes credentials."""
    request = urllib.request.Request(
        "http://127.0.0.1:8788/speech",
        data=json.dumps({"text": text}).encode("utf-8"), method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoSpeechRedirect())
    return opener.open(request, timeout=20)


def _cloud_speech_text(text: str, config) -> str:
    # The app token, Hermes key and provider key must never become TTS content.
    for key in (config.app_token, config.hermes_key, config.elevenlabs_key):
        if key:
            text = text.replace(key, "[geschützt]")
    for pattern in (
        r"-----BEGIN [A-Z ]+-----.*?-----END [A-Z ]+-----",
        r"(?i)\b(?:api[_-]?key|secret|password|passwd|token|bearer|authorization)\b\s*[:=]\s*\S+",
        r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]+=*",
        r"\b(?:sk|pk|key|tok|ghp|xox[abp])[-_][A-Za-z0-9_-]{12,}\b",
        r"\b[A-Za-z0-9+/_-]{36,}\b",
    ):
        text = re.sub(pattern, "[geschützt]", text, flags=re.DOTALL)
    return text


def _elevenlabs_payload(text: str, config) -> dict:
    payload = {
        "text": _cloud_speech_text(text, config),
        "model_id": config.elevenlabs_model,
        "voice_settings": {
            "stability": config.elevenlabs_stability,
            "similarity_boost": config.elevenlabs_similarity,
            "style": config.elevenlabs_style,
            "use_speaker_boost": False,
        },
    }
    if config.elevenlabs_model in LANGUAGE_CODE_MODELS:
        payload["language_code"] = "de"
    return payload


UPLOAD_DIR = Path.home() / ".hermes" / "jarvis-uploads"
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
# Recognised by content, never by a client-supplied name or type. A caller must
# not be able to talk the bridge into writing an executable or a .env.
IMAGE_MAGIC = (
    (b"\x89PNG\r\n\x1a\n", ".png"),
    (b"\xff\xd8\xff", ".jpg"),
    (b"GIF87a", ".gif"),
    (b"GIF89a", ".gif"),
)


def _sniff_image(blob: bytes) -> str:
    for magic, suffix in IMAGE_MAGIC:
        if blob.startswith(magic):
            return suffix
    if blob[:4] == b"RIFF" and blob[8:12] == b"WEBP":
        return ".webp"
    if blob[4:8] == b"ftyp" and blob[8:12] in (b"heic", b"heix", b"mif1", b"msf1"):
        return ".heic"
    raise ValueError("Nur Bilder werden angenommen")


def message_with_image(message: str, image_path: str) -> str:
    """Point the agent at a pasted image, but only inside the upload folder.

    A client-supplied path is otherwise a way to make the agent read any file
    on the Mac, so anything outside UPLOAD_DIR is refused rather than trusted.
    """
    if not image_path:
        return message
    candidate = Path(image_path).expanduser()
    try:
        resolved = candidate.resolve(strict=True)
        root = UPLOAD_DIR.resolve()
    except OSError as exc:
        raise ValueError("Bild nicht gefunden") from exc
    if root not in resolved.parents or not resolved.is_file():
        raise ValueError("Bild liegt nicht im Uploadordner")
    return (f"[Der Nutzer hat ein Bild angehängt: {resolved}. "
            f"Sieh es dir mit vision_analyze an, bevor du antwortest.]\n{message}")


def store_upload(encoded: str) -> Path:
    """Write a pasted image to a fixed directory under a generated name."""
    if not isinstance(encoded, str) or len(encoded) > MAX_UPLOAD_BYTES * 4 // 3 + 1024:
        raise ValueError("Bild ist zu groß")
    try:
        blob = base64.b64decode(encoded, validate=True)
    except Exception as exc:  # noqa: BLE001
        raise ValueError("Bild konnte nicht gelesen werden") from exc
    if not blob or len(blob) > MAX_UPLOAD_BYTES:
        raise ValueError("Bild ist zu groß")
    suffix = _sniff_image(blob)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(UPLOAD_DIR, 0o700)
    destination = UPLOAD_DIR / f"{secrets.token_hex(16)}{suffix}"
    destination.write_bytes(blob)
    os.chmod(destination, 0o600)
    return destination


IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".bmp", ".svg")
VIDEO_SUFFIXES = (".mp4", ".mov", ".webm", ".m4v")
VIDEO_HOSTS = ("youtube.com", "youtu.be", "vimeo.com", "dailymotion.com")
MARKDOWN_LINK = re.compile(r"(!?)\[([^\]\n]{0,120})\]\((https?://[^\s)]{1,600})\)")
BARE_URL = re.compile(r"(?<![(\]<])\bhttps?://[^\s<>\"')\]]{1,600}")
MAX_ATTACHMENTS = 12


def _attachment_kind(url: str, forced_image: bool) -> str:
    if forced_image:
        return "image"
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower().removeprefix("www.")
    path = parsed.path.lower()
    if any(host == known or host.endswith("." + known) for known in VIDEO_HOSTS):
        return "video"
    if path.endswith(VIDEO_SUFFIXES):
        return "video"
    if path.endswith(IMAGE_SUFFIXES):
        return "image"
    return "source"


def extract_attachments(text: str) -> list[dict]:
    """Turn links in the answer into things the app can show.

    Only http and https survive: a data: or file: URL rendered by the app would
    reach into the device or embed arbitrary bytes. Order and first-occurrence
    wins, so the answer's own emphasis is preserved.
    """
    found: dict[str, dict] = {}
    for bang, title, url in MARKDOWN_LINK.findall(text or ""):
        if url not in found:
            found[url] = {"kind": _attachment_kind(url, bang == "!"),
                          "url": url, "title": title.strip()[:120]}
    for url in BARE_URL.findall(text or ""):
        url = url.rstrip(".,;:!?")
        if url not in found:
            found[url] = {"kind": _attachment_kind(url, False), "url": url, "title": ""}
    result = []
    for item in found.values():
        if not item["title"]:
            host = (urlparse(item["url"]).hostname or "").removeprefix("www.")
            item["title"] = host[:120]
        result.append(item)
        if len(result) >= MAX_ATTACHMENTS:
            break
    return result


# The provider's catalogue changes rarely and a request must never wait on it.
_VOICE_CACHE: dict[str, object] = {"at": 0.0, "voices": []}
_VOICE_CACHE_TTL = 900
_VOICE_CACHE_LOCK = threading.Lock()


def _fetch_elevenlabs_voices(config) -> list[dict]:
    """Names and ids only. The API key stays on the Mac; clients never see it."""
    request = urllib.request.Request(
        "https://api.elevenlabs.io/v1/voices?page_size=100",
        headers={"xi-api-key": config.elevenlabs_key},
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoSpeechRedirect())
    with opener.open(request, timeout=20) as response:
        payload = json.loads(response.read(2_000_000).decode("utf-8"))
    voices = []
    for entry in payload.get("voices", [])[:100]:
        voice_id = str(entry.get("voice_id") or "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{10,80}", voice_id):
            continue
        labels = entry.get("labels") or {}
        voices.append({
            "id": voice_id,
            "name": str(entry.get("name") or voice_id)[:80],
            "accent": str(labels.get("accent") or "")[:40],
            "gender": str(labels.get("gender") or "")[:20],
            "description": str(labels.get("descriptive") or entry.get("description") or "")[:160],
        })
    return voices


def elevenlabs_voices(config, force: bool = False) -> list[dict]:
    with _VOICE_CACHE_LOCK:
        fresh = time.monotonic() - float(_VOICE_CACHE["at"]) < _VOICE_CACHE_TTL
        if not force and fresh and _VOICE_CACHE["voices"]:
            return list(_VOICE_CACHE["voices"])  # type: ignore[arg-type]
    voices = _fetch_elevenlabs_voices(config)
    with _VOICE_CACHE_LOCK:
        _VOICE_CACHE["at"] = time.monotonic()
        _VOICE_CACHE["voices"] = voices
    return list(voices)


def resolve_voice_id(requested: str, config) -> str:
    """A client may only pick a voice the account actually offers.

    Without this the app could make the bridge spend the user's provider quota
    on any id it liked. On a lookup failure the configured voice is used.
    """
    if not requested:
        return config.elevenlabs_voice_id
    if not re.fullmatch(r"[A-Za-z0-9_-]{10,80}", requested):
        raise ValueError("Ungültige Stimme")
    try:
        allowed = {voice["id"] for voice in elevenlabs_voices(config)}
    except Exception:  # noqa: BLE001
        return config.elevenlabs_voice_id
    if requested not in allowed:
        raise ValueError("Unbekannte Stimme")
    return requested


def _open_elevenlabs_speech(text: str, config, voice_id: str = ""):
    voice = voice_id or config.elevenlabs_voice_id
    if not config.elevenlabs_key or not re.fullmatch(r"[A-Za-z0-9_-]{10,80}", voice):
        raise ValueError("ElevenLabs key and voice are required")
    request = urllib.request.Request(
        "https://api.elevenlabs.io/v1/text-to-speech/"
        + voice + "/stream?output_format=pcm_24000",
        data=json.dumps(_elevenlabs_payload(text, config)).encode("utf-8"), method="POST",
        headers={"xi-api-key": config.elevenlabs_key, "Content-Type": "application/json"},
    )
    # Fixed TLS origin. Neither environment proxies nor redirects may receive keys.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoSpeechRedirect())
    return opener.open(request, timeout=20)


def _pcm_frames(upstream):
    pending = b""
    total = 0
    # read1 returns available bytes rather than waiting to fill a large buffer.
    read = getattr(upstream, "read1", upstream.read)
    while True:
        chunk = read(8192)
        if not chunk:
            break
        total += len(chunk)
        if total > 24_000 * 2 * 60:
            raise ValueError("Audio limit")
        pending += chunk
        length = len(pending) - len(pending) % 2
        if length:
            yield {"type": "audio", "sample_rate": 24000, "format": "pcm_s16le",
                   "data": base64.b64encode(pending[:length]).decode("ascii")}
            pending = pending[length:]
    if pending or not total:
        raise ValueError("Incomplete audio")
    yield {"type": "done"}


class HermesClient:
    def __init__(self, config: BridgeConfig):
        self.config = config
        self._state_lock = threading.Lock()
        self._conversation_locks: dict[str, threading.Lock] = {}
        # Hermes announces run.started at the *beginning* of the SSE stream, so
        # the run id is known while the turn is still running even though /chat
        # only returns it at the end. Recording it here is what makes a
        # conversation-scoped stop possible for clients that never see the id.
        # client_run_id -> {"run_id": str, "cancelled": bool}
        self._client_runs: dict[str, dict] = {}
        self._active_runs_lock = threading.Lock()

    def _headers(self, accept: str = "application/json") -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.config.hermes_key}",
            "Content-Type": "application/json",
            "Accept": accept,
            "X-Hermes-Session-Key": self.config.session_key,
        }

    def _request(self, method: str, path: str, payload: dict | None = None, timeout: int = 20):
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self.config.hermes_url + path,
            data=data,
            method=method,
            headers=self._headers(),
        )
        return urllib.request.urlopen(request, timeout=timeout)

    def health(self) -> dict:
        try:
            with self._request("GET", "/health", timeout=5) as response:
                body = json.loads(response.read().decode("utf-8"))
            return {"ok": True, "hermes": body}
        except Exception as exc:
            return {"ok": False, "error": self._safe_error(exc)}

    def _load_state(self) -> dict[str, str]:
        try:
            data = json.loads(self.config.state_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_state(self, state: dict[str, str]) -> None:
        self.config.state_path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.config.state_path.with_suffix(".tmp")
        temp.write_text(json.dumps(state, indent=2), encoding="utf-8")
        os.chmod(temp, 0o600)
        temp.replace(self.config.state_path)

    def _session_id_by_title(self, title: str) -> str:
        """Find an existing Hermes session by exact title, or "" if there is none.

        Uses the gateway's exact-title query rather than scanning a listing page:
        the default listing is capped (limit=50, recency-ordered) and excludes
        hidden and child sessions, so a plain scan misses precisely the old or
        hidden session that a duplicate-title 400 is complaining about.

        An HTTP failure here is raised, not swallowed, so a 401 or 500 on this
        call is never reported as the earlier duplicate-title 400. Note that
        HTTPError subclasses URLError, so it must be re-raised explicitly.
        """
        # The gateway's `title` filter feeds a SUBSTRING search and only then
        # applies exact matching, and it is still capped by `limit`. So ask for
        # the maximum page and include child sessions: otherwise a title that
        # many newer sessions merely contain, or one held by a child session,
        # pushes the exact row out of view and recovery fails.
        matches: list[dict] = []
        for page in range(LOOKUP_MAX_PAGES):
            path = (f"/api/sessions?title={quote(title, safe='')}"
                    "&include_hidden=true&include_children=true"
                    f"&limit={LOOKUP_PAGE}&offset={page * LOOKUP_PAGE}")
            try:
                with self._request("GET", path) as response:
                    payload = json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError:
                raise
            except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
                # Do not return "" here: the caller would re-raise the earlier
                # duplicate-title 400 and hide the real cause of this failure.
                raise RuntimeError(
                    f"Hermes session lookup failed: {type(exc).__name__}") from exc
            sessions = payload.get("data") if isinstance(payload, dict) else payload
            sessions = sessions or []
            matches = [
                s for s in sessions
                if isinstance(s, dict)
                and (s.get("title") or "").strip() == title
                and s.get("id")
            ]
            if matches:
                break
            # Deliberately no short-page break: the gateway filters for the
            # exact title server-side, so `data` is already tiny (usually
            # empty) even when 200 substring matches were scanned. Its length
            # says nothing about whether more rows exist.
        if not matches:
            return ""
        # Title uniqueness in Hermes is global, so a CLI- or peer-owned session
        # can hold this title too. Adopt only a session this bridge could have
        # created. Silently writing the phone's messages into someone else's
        # transcript is worse than refusing to continue.
        for session in matches:
            if session.get("source") == "api_server":
                return str(session["id"])
        foreign = matches[0]
        raise RuntimeError(
            f"Session title {title!r} is held by session {foreign.get('id')} "
            f"from source {foreign.get('source')!r}, not by this bridge. "
            "Rename or remove that session, or pick another conversation name.")

    def _create_or_adopt(self, conversation: str) -> str:
        try:
            with self._request("POST", "/api/sessions", {"title": conversation}) as response:
                data = json.loads(response.read().decode("utf-8"))
            return str((data.get("session") or data).get("id") or "")
        except urllib.error.HTTPError as exc:
            # Hermes rejects a duplicate title with 400. That happens whenever
            # the local state file is lost, truncated, or never held an entry
            # for a conversation that already exists server-side. Without this
            # recovery every later turn fails with 502 forever, on the app and
            # on any other bridge client.
            if exc.code != HTTPStatus.BAD_REQUEST:
                raise
            session_id = self._session_id_by_title(conversation)
            if not session_id:
                raise
            return session_id

    def _session_id(self, conversation: str, force_new: bool = False) -> str:
        with self._state_lock:
            if not force_new:
                cached = self._load_state().get(conversation)
                # Validate on read as well: an id written by an older build (or
                # a hand-edited state file) is interpolated into a URL path just
                # the same, so it cannot be trusted merely because it is cached.
                if cached and SESSION_ID_RE.fullmatch(str(cached)):
                    return str(cached)

        # Deliberately outside _state_lock: this makes up to two gateway calls,
        # and _state_lock is global. Holding it here would block every other
        # conversation's thread for the duration. chat() already serializes
        # turns per conversation, so two threads cannot race on the same key.
        session_id = self._create_or_adopt(conversation)
        if not session_id:
            raise RuntimeError("Hermes returned no session id")
        if not SESSION_ID_RE.fullmatch(session_id):
            raise RuntimeError("Hermes returned a malformed session id")

        with self._state_lock:
            state = self._load_state()
            state[conversation] = session_id
            self._save_state(state)
        return session_id

    def _lock_for(self, conversation: str) -> threading.Lock:
        with self._state_lock:
            return self._conversation_locks.setdefault(conversation, threading.Lock())

    def chat(self, text: str, conversation: str, client_run_id: str = "", on_event=None) -> dict:
        if client_run_id:
            # Registered before the lock so a /stop arriving while this turn is
            # still queued behind another client is remembered, not lost.
            with self._active_runs_lock:
                if client_run_id in self._client_runs:
                    raise ValueError("client_run_id ist bereits aktiv")
                self._client_runs[client_run_id] = {"cancelled": False, "phase": "queued"}
        try:
            with self._lock_for(conversation):
                if client_run_id:
                    with self._active_runs_lock:
                        if self._client_runs.get(client_run_id, {}).get("cancelled"):
                            raise RuntimeError("Abgebrochen, bevor der Turn startete")
                try:
                    return self._chat_once(text, conversation, False, client_run_id, **({"on_event": on_event} if on_event else {}))
                except urllib.error.HTTPError as exc:
                    if exc.code != HTTPStatus.NOT_FOUND:
                        raise
                    return self._chat_once(text, conversation, True, client_run_id, **({"on_event": on_event} if on_event else {}))
        finally:
            if client_run_id:
                # chat() owns the entry's lifetime: it is created before the
                # conversation lock and removed only when the whole turn,
                # including the one 404 retry, is finished.
                with self._active_runs_lock:
                    self._client_runs.pop(client_run_id, None)

    def _chat_once(self, text: str, conversation: str, force_new: bool,
                   client_run_id: str = "", on_event=None) -> dict:
        self._set_activity(client_run_id, "thinking")
        session_id = self._session_id(conversation, force_new=force_new)
        request = urllib.request.Request(
            f"{self.config.hermes_url}/api/sessions/{session_id}/chat/stream",
            data=json.dumps({"input": f"{_now_context()}\n{text}"}).encode("utf-8"),
            method="POST",
            headers=self._headers("text/event-stream"),
        )
        parts: list[str] = []
        tools: list[dict] = []
        # Assistant text is buffered here until it is clear that no tool call
        # follows it. See the assistant.delta branch below.
        pending: list[str] = []
        announced_text = False
        run_id = ""
        try:
            with urllib.request.urlopen(request, timeout=300) as response:
                for event, data in parse_sse(response):
                    if event == "run.started":
                        run_id = str(data.get("run_id") or "")
                        if run_id and client_run_id:
                            with self._active_runs_lock:
                                entry = self._client_runs.setdefault(client_run_id, {})
                                entry["run_id"] = run_id
                                already_cancelled = bool(entry.get("cancelled"))
                            # A /stop can land before the run even exists. Honour
                            # it now instead of letting the turn run to the end.
                            if already_cancelled:
                                try:
                                    self.stop(run_id)
                                except Exception:  # noqa: BLE001
                                    pass
                    elif event == "assistant.delta":
                        self._set_activity(client_run_id, "answering")
                        delta = str(data.get("delta") or "")
                        parts.append(delta)
                        # Held back, not forwarded. Text written before a tool
                        # call is the model thinking out loud ("Lass mich die
                        # Dateien lesen"). Spoken aloud that is minutes of
                        # narration the user never asked for, so a segment is
                        # only released once it is known to be the answer.
                        pending.append(delta)
                        # A frame still has to reach the client while text is
                        # being produced: it is the only way a disconnect is
                        # noticed, and it is the short form the user sees
                        # instead of the narration. Once per segment is enough.
                        if on_event and not announced_text:
                            announced_text = True
                            on_event({"type": "activity", **self.activity(client_run_id)})
                    elif event == "tool.started":
                        name = str(data.get("tool_name") or "tool")
                        # Whatever was written before this tool call was
                        # narration. Drop it; the activity label is the short
                        # form the user sees instead.
                        pending.clear()
                        announced_text = False
                        if not name.startswith("_"):
                            self._set_activity(client_run_id, "tool", name)
                            if on_event:
                                on_event({"type": "activity", **self.activity(client_run_id)})
                            tools.append({
                                "name": name,
                                "preview": str(data.get("preview") or "")[:200],
                            })
                    elif event == "assistant.completed" and data.get("content"):
                        parts = [str(data["content"])]
                        # No tool followed, so the held text was the answer.
                        # Release it now so the app can show and speak it.
                        if on_event and pending:
                            on_event({"type": "delta", "text": "".join(pending)})
                        pending.clear()
                    elif event in {"run.failed", "error"}:
                        raise RuntimeError(str(data.get("error") or data.get("message") or "Hermes run failed"))
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            if run_id:
                try:
                    self.stop(run_id)
                except Exception:
                    pass
            raise
        finally:
            # Must be a finally: run.failed raises, and a dropped connection or
            # read timeout escapes too. Leaving the entry behind would let a
            # later conversation-scoped /stop resolve a dead run id and report
            # a successful cancellation for a turn that was never stopped.
            if client_run_id:
                with self._active_runs_lock:
                    entry = self._client_runs.get(client_run_id)
                    # Unbind, do not delete: chat() retries once on 404 and owns
                    # the entry's lifetime. Deleting here would drop a cancel
                    # that arrived during session recovery.
                    if entry is not None:
                        entry.pop("run_id", None)
        answer = "".join(parts).strip()
        return {"text": answer, "tools": tools, "run_id": run_id,
                "attachments": extract_attachments(answer)}

    def _set_activity(self, client_run_id: str, phase: str, tool: str = "") -> None:
        # Status exposes tool identifiers only: never arguments, output or text.
        safe_tool = tool if re.fullmatch(r"[A-Za-z0-9_.:-]{1,100}", tool) else ""
        with self._active_runs_lock:
            entry = self._client_runs.get(client_run_id)
            if entry is not None:
                entry.update(phase=phase, tool=safe_tool)

    def activity(self, client_run_id: str) -> dict:
        with self._active_runs_lock:
            entry = self._client_runs.get(client_run_id)
            if entry is None:
                return {"phase": "unknown", "tool": ""}
            return {"phase": "stopping" if entry.get("cancelled") else entry.get("phase", "thinking"),
                    "tool": entry.get("tool", "")}

    def cancel_client_run(self, client_run_id: str) -> dict:
        """Cancel only the turn this caller started.

        The conversation is shared, so cancelling "the conversation" could stop
        another surface's turn. A caller can therefore only ever address its own
        run. If the run has not reached run.started yet, the request is recorded
        and applied the moment it does.
        """
        with self._active_runs_lock:
            entry = self._client_runs.get(client_run_id)
            if entry is None:
                return {"status": "unknown", "stopped": False,
                        "error": "Kein laufender Turn mit dieser client_run_id"}
            entry["cancelled"] = True
            run_id = entry.get("run_id") or ""
        if not run_id:
            return {"status": "pending", "stopped": False,
                    "error": "Turn hat noch nicht begonnen; Abbruch ist vorgemerkt"}
        result = self.stop(run_id)
        # Hermes answers "stopping": it has accepted an interrupt, not proven the
        # run is dead. Only claim stopped when it actually says so.
        status = str(result.get("status") or "stopping")
        result["stopped"] = status == "stopped"
        result["status"] = status
        result["run_id"] = run_id
        return result

    def stop(self, run_id: str) -> dict:
        if not RUN_ID_RE.fullmatch(run_id):
            raise ValueError("Ungültige run_id")
        with self._request("POST", f"/v1/runs/{run_id}/stop", {}) as response:
            raw = response.read().decode("utf-8")
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"status": "stopped"}

    @staticmethod
    def _safe_error(exc: Exception) -> str:
        if isinstance(exc, urllib.error.HTTPError):
            return f"Hermes HTTP {exc.code}"
        if isinstance(exc, urllib.error.URLError):
            return "Hermes ist nicht erreichbar"
        return str(exc)[:240]


class JarvisHandler(BaseHTTPRequestHandler):
    server_version = "JarvisBridge/1.0"
    client: HermesClient
    config: BridgeConfig

    def log_message(self, fmt: str, *args) -> None:
        print(f"{self.address_string()} - {fmt % args}")

    def _token(self) -> str:
        auth = self.headers.get("Authorization", "")
        if auth.lower().startswith("bearer "):
            return auth[7:].strip()
        return self.headers.get("X-Jarvis-Token", "").strip()

    def _authorized(self) -> bool:
        return constant_time_token_matches(self.config.app_token, self._token())

    def _json(self, status: int, body: dict) -> None:
        encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(encoded)

    def _resolve_file(self, raw_path: str) -> Path:
        candidate = Path(unquote(raw_path)).expanduser().resolve()
        allowed = any(candidate == root or root in candidate.parents for root in self.config.file_roots)
        if not allowed:
            raise PermissionError("Pfad ist nicht freigegeben")
        relative_parts: tuple[str, ...] = ()
        for root in self.config.file_roots:
            if candidate == root or root in candidate.parents:
                relative_parts = candidate.relative_to(root).parts
                break
        if any(part in BLOCKED_PATH_PARTS for part in relative_parts):
            raise PermissionError("Sicherheitsrelevanter Ordner ist gesperrt")
        if candidate.name == ".env" or candidate.suffix.lower() in BLOCKED_FILE_SUFFIXES:
            raise PermissionError("Sicherheitsrelevante Datei ist gesperrt")
        return candidate

    def _file_listing(self, path: Path) -> dict:
        if not path.is_dir():
            raise ValueError("Pfad ist kein Ordner")
        items = []
        for item in sorted(path.iterdir(), key=lambda value: (not value.is_dir(), value.name.lower())):
            if item.name.startswith(".") or item.name in BLOCKED_PATH_PARTS:
                continue
            try:
                stat = item.stat()
            except OSError:
                continue
            items.append({
                "name": item.name,
                "path": str(item),
                "is_directory": item.is_dir(),
                "size": 0 if item.is_dir() else stat.st_size,
                "modified": stat.st_mtime,
            })
        return {"path": str(path), "parent": str(path.parent), "items": items[:1000]}

    def _download(self, path: Path) -> None:
        if not path.is_file():
            raise FileNotFoundError("Datei nicht gefunden")
        size = path.stat().st_size
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(size))
        safe_name = path.name.replace('"', "")
        self.send_header("Content-Disposition", f'attachment; filename="{safe_name}"')
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        with path.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                self.wfile.write(chunk)

    def _body(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("Ungültige Anfrage") from exc
        if length <= 0 or length > MAX_BODY_BYTES:
            raise ValueError("Ungültige Anfragegröße")
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def _handle_wake(self) -> None:
        relay_url = self.config.relay_url
        if not relay_url:
            self._json(HTTPStatus.OK, {"awake": True, "relay": False})
            return
        request = urllib.request.Request(
            relay_url.rstrip("/") + "/wake",
            data=b"",
            method="POST",
            headers={
                "Authorization": f"Bearer {self.config.app_token}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                relay_body = response.read().decode("utf-8")
        except Exception as exc:
            self._json(HTTPStatus.BAD_GATEWAY, {"error": HermesClient._safe_error(exc)})
            return
        try:
            data = json.loads(relay_body)
        except json.JSONDecodeError:
            data = {}
        data["awake"] = True
        data["relay"] = True
        self._json(HTTPStatus.OK, data)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._json(HTTPStatus.OK, {"service": "JARVIS Bridge", "auth": "required"})
            return
        if not self._authorized():
            self._json(HTTPStatus.UNAUTHORIZED, {"error": "Nicht autorisiert"})
            return
        if parsed.path == "/voices":
            provider = getattr(self.config, "speech_provider", "local")
            if provider != "elevenlabs":
                self._json(HTTPStatus.OK, {"provider": provider, "voices": [], "selected": ""})
                return
            try:
                force = parse_qs(parsed.query).get("refresh", ["0"])[0] == "1"
                voices = elevenlabs_voices(self.config, force=force)
            except Exception:  # noqa: BLE001
                self._json(503, {"error": "Stimmenliste nicht verfügbar."})
                return
            self._json(HTTPStatus.OK, {"provider": provider, "voices": voices,
                                       "selected": self.config.elevenlabs_voice_id})
            return
        if parsed.path == "/activity":
            values = parse_qs(parsed.query).get("client_run_id", [])
            if len(values) != 1 or not CLIENT_RUN_ID_RE.fullmatch(values[0]):
                self._json(HTTPStatus.BAD_REQUEST, {"error": "Ungültige client_run_id"})
                return
            self._json(HTTPStatus.OK, self.client.activity(values[0]))
            return
        if parsed.path == "/health":
            health = self.client.health()
            status = HTTPStatus.OK if health["ok"] else HTTPStatus.SERVICE_UNAVAILABLE
            self._json(status, health)
            return
        if parsed.path in {"/files", "/files/download"}:
            try:
                values = parse_qs(parsed.query)
                requested = values.get("path", [str(self.config.file_roots[0])])[0]
                path = self._resolve_file(requested)
                if parsed.path == "/files":
                    self._json(HTTPStatus.OK, self._file_listing(path))
                else:
                    self._download(path)
            except PermissionError as exc:
                self._json(HTTPStatus.FORBIDDEN, {"error": str(exc)})
            except (OSError, ValueError) as exc:
                self._json(HTTPStatus.NOT_FOUND, {"error": str(exc)})
            return
        self._json(HTTPStatus.NOT_FOUND, {"error": "Nicht gefunden"})

    def _handle_speech(self, body: dict) -> None:
        text = body.get("text")
        if not isinstance(text, str) or not 1 <= len(text.strip()) <= 600:
            raise ValueError("Sprachtext muss 1 bis 600 Zeichen enthalten")
        requested_voice = body.get("voice_id") or ""
        if not isinstance(requested_voice, str) or len(requested_voice) > 80:
            raise ValueError("Ungültige Stimme")
        provider = getattr(self.config, "speech_provider", "local")
        if provider == "elevenlabs":
            try:
                voice = resolve_voice_id(requested_voice.strip(), self.config)
            except ValueError as exc:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return
            self._handle_elevenlabs_speech(text.strip(), voice)
            return
        if provider != "local":
            self._json(503, {"error": "Sprachanbieter nicht konfiguriert"})
            return
        try:
            upstream = _open_neural_speech(text.strip(), self.config.app_token)
        except urllib.error.HTTPError as exc:
            self._json(429 if exc.code == 429 else 503, {"error": "Neuronale Stimme nicht verfügbar"})
            return
        except Exception:
            self._json(503, {"error": "Neuronale Stimme nicht verfügbar"})
            return
        with upstream:
            self.send_response(200)
            self.send_header("X-JARVIS-Speech-Provider", "local")
            self.send_header("Content-Type", "application/x-ndjson")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            try:
                total = 0
                while True:
                    line = upstream.readline(800_000)
                    if not line:
                        break
                    total += len(line)
                    if len(line) >= 800_000 or total > 4_000_000 or not line.endswith(b"\n"):
                        raise ValueError("Speech stream limit")
                    self.wfile.write(line)
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                return
            except Exception:
                try:
                    self.wfile.write(b'{"type":"error","error":"Sprachausgabe unterbrochen"}\n')
                    self.wfile.flush()
                except OSError:
                    pass

    def _handle_elevenlabs_speech(self, text: str, voice_id: str = "") -> None:
        try:
            upstream = _open_elevenlabs_speech(text, self.config, voice_id)
        except urllib.error.HTTPError as exc:
            # 402 means the account lists the voice but the plan may not use it.
            # Library voices appear in /voices on every tier yet only paid plans
            # can synthesise with them, so say that instead of "unavailable".
            if exc.code == 402:
                self._json(402, {"error": "Diese Stimme gehört zur ElevenLabs-Bibliothek "
                                          "und benötigt einen bezahlten Tarif. Wähle eine "
                                          "der vorinstallierten Stimmen."})
                return
            self._json(429 if exc.code == 429 else 503,
                       {"error": "ElevenLabs nicht verfügbar. Konto und Kontingent prüfen."})
            return
        except Exception:
            self._json(503, {"error": "ElevenLabs-Stimme noch nicht eingerichtet oder nicht erreichbar."})
            return
        with upstream:
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.send_header("X-JARVIS-Speech-Provider", "elevenlabs")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            try:
                for frame in _pcm_frames(upstream):
                    self.wfile.write(json.dumps(frame).encode() + b"\n")
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, TimeoutError):
                pass
            except Exception:
                try:
                    self.wfile.write(b'{"type":"error","error":"Sprachausgabe unterbrochen"}\n')
                    self.wfile.flush()
                except OSError:
                    pass

    def _handle_chat_stream(self, message: str, conversation: str, client_run_id: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True

        def emit(frame):
            self.wfile.write(json.dumps(frame, ensure_ascii=False).encode("utf-8") + b"\n")
            self.wfile.flush()

        started = time.monotonic()
        try:
            emit({"type": "activity", "phase": "thinking", "tool": ""})
            result = self.client.chat(message, conversation, client_run_id, on_event=emit)
            result["duration_ms"] = round((time.monotonic() - started) * 1000)
            emit({"type": "done", "response": result})
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            pass
        except Exception:
            # Stream is already HTTP 200. Never write a second HTTP response,
            # or expose provider exception strings in an error frame.
            try:
                emit({"type": "error", "error": "Antwort unterbrochen. Bitte erneut versuchen."})
            except OSError:
                pass

    def do_POST(self) -> None:
        if not self._authorized():
            self._json(HTTPStatus.UNAUTHORIZED, {"error": "Nicht autorisiert"})
            return
        try:
            body = self._body()
            if self.path == "/upload":
                try:
                    stored = store_upload(body.get("data") or "")
                except ValueError as exc:
                    self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                    return
                self._json(HTTPStatus.OK, {"path": str(stored), "name": stored.name})
                return
            if self.path == "/speech":
                self._handle_speech(body)
                return
            if self.path in {"/chat", "/chat/stream"}:
                message = str(body.get("message") or "").strip()
                conversation = str(body.get("conversation") or "jarvis-apple").strip()
                if not message or len(message) > 20_000:
                    raise ValueError("Nachricht fehlt oder ist zu lang")
                if not conversation or len(conversation) > 80:
                    raise ValueError("Ungültige Unterhaltung")
                image_path = str(body.get("image_path") or "").strip()
                if len(image_path) > 4096:
                    raise ValueError("Ungültiger Bildpfad")
                message = message_with_image(message, image_path)
                client_run_id = str(body.get("client_run_id") or "").strip()
                if client_run_id and not CLIENT_RUN_ID_RE.fullmatch(client_run_id):
                    raise ValueError("Ungültige client_run_id")
                if self.path == "/chat/stream":
                    if not client_run_id:
                        raise ValueError("client_run_id fehlt")
                    self._handle_chat_stream(message, conversation, client_run_id)
                    return
                started = time.monotonic()
                result = self.client.chat(message, conversation, client_run_id)
                result["duration_ms"] = round((time.monotonic() - started) * 1000)
                self._json(HTTPStatus.OK, result)
                return
            if self.path == "/stop":
                run_id = str(body.get("run_id") or "").strip()
                # A client that only sees the synchronous /chat response cannot
                # know the Hermes run id while its turn is running. It passes a
                # client_run_id to /chat and cancels with that instead. Note it
                # is NOT possible to cancel "the conversation": several surfaces
                # share it, so that would stop someone else's turn.
                client_run_id = str(body.get("client_run_id") or "").strip()
                if run_id and client_run_id:
                    raise ValueError("run_id und client_run_id schließen sich aus")
                if client_run_id:
                    if not CLIENT_RUN_ID_RE.fullmatch(client_run_id):
                        raise ValueError("Ungültige client_run_id")
                    self._json(HTTPStatus.OK,
                               self.client.cancel_client_run(client_run_id))
                    return
                if not run_id:
                    raise ValueError("run_id oder client_run_id fehlt")
                result = self.client.stop(run_id)
                status = str(result.get("status") or "stopping")
                result["status"] = status
                result["stopped"] = status == "stopped"
                result["run_id"] = run_id
                self._json(HTTPStatus.OK, result)
                return
            if self.path == "/wake":
                self._handle_wake()
                return
            self._json(HTTPStatus.NOT_FOUND, {"error": "Nicht gefunden"})
        except ValueError as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        except urllib.error.HTTPError as exc:
            self._json(HTTPStatus.BAD_GATEWAY, {"error": f"Hermes HTTP {exc.code}"})
        except Exception as exc:
            self._json(HTTPStatus.BAD_GATEWAY, {"error": HermesClient._safe_error(exc)})


def make_server(config: BridgeConfig) -> ThreadingHTTPServer:
    handler = type("ConfiguredJarvisHandler", (JarvisHandler,), {})
    handler.client = HermesClient(config)
    handler.config = config
    return ThreadingHTTPServer((config.host, config.port), handler)


def main() -> None:
    parser = argparse.ArgumentParser(description="Native JARVIS app bridge")
    parser.add_argument("--host", default=os.environ.get("JARVIS_BRIDGE_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("JARVIS_BRIDGE_PORT", "8770")))
    parser.add_argument("--generate-token", action="store_true", help="print a new app token and exit")
    args = parser.parse_args()
    if args.generate_token:
        print(secrets.token_urlsafe(32))
        return
    config = BridgeConfig.from_environment(args.host, args.port)
    server = make_server(config)
    print(f"JARVIS Bridge listening on http://{config.host}:{config.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
