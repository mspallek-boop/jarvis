#!/usr/bin/env python3
"""Small authenticated bridge between the native JARVIS app and Hermes Agent.

It deliberately uses only Python's standard library. Hermes' powerful API key
never leaves the Mac; clients only receive a separate JARVIS app token.
"""

from __future__ import annotations

import argparse
import hmac
import json
import os
import secrets
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Iterator
from urllib.parse import urlparse
from urllib.parse import parse_qs, unquote


DEFAULT_ENV = Path.home() / ".hermes" / ".env"
DEFAULT_STATE = Path.home() / ".hermes" / "jarvis-app-sessions.json"
MAX_BODY_BYTES = 64 * 1024
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
        )


class HermesClient:
    def __init__(self, config: BridgeConfig):
        self.config = config
        self._state_lock = threading.Lock()
        self._conversation_locks: dict[str, threading.Lock] = {}

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

    def _session_id(self, conversation: str, force_new: bool = False) -> str:
        with self._state_lock:
            state = self._load_state()
            if not force_new and state.get(conversation):
                return state[conversation]
            with self._request("POST", "/api/sessions", {"title": conversation}) as response:
                data = json.loads(response.read().decode("utf-8"))
            session_id = str((data.get("session") or data).get("id") or "")
            if not session_id:
                raise RuntimeError("Hermes returned no session id")
            state[conversation] = session_id
            self._save_state(state)
            return session_id

    def _lock_for(self, conversation: str) -> threading.Lock:
        with self._state_lock:
            return self._conversation_locks.setdefault(conversation, threading.Lock())

    def chat(self, text: str, conversation: str) -> dict:
        with self._lock_for(conversation):
            try:
                return self._chat_once(text, conversation, force_new=False)
            except urllib.error.HTTPError as exc:
                if exc.code != HTTPStatus.NOT_FOUND:
                    raise
                return self._chat_once(text, conversation, force_new=True)

    def _chat_once(self, text: str, conversation: str, force_new: bool) -> dict:
        session_id = self._session_id(conversation, force_new=force_new)
        request = urllib.request.Request(
            f"{self.config.hermes_url}/api/sessions/{session_id}/chat/stream",
            data=json.dumps({"input": text}).encode("utf-8"),
            method="POST",
            headers=self._headers("text/event-stream"),
        )
        parts: list[str] = []
        tools: list[dict] = []
        run_id = ""
        with urllib.request.urlopen(request, timeout=300) as response:
            for event, data in parse_sse(response):
                if event == "run.started":
                    run_id = str(data.get("run_id") or "")
                elif event == "assistant.delta":
                    parts.append(str(data.get("delta") or ""))
                elif event == "tool.started":
                    name = str(data.get("tool_name") or "tool")
                    if not name.startswith("_"):
                        tools.append({
                            "name": name,
                            "preview": str(data.get("preview") or "")[:200],
                        })
                elif event == "assistant.completed" and data.get("content"):
                    parts = [str(data["content"])]
                elif event in {"run.failed", "error"}:
                    raise RuntimeError(str(data.get("error") or data.get("message") or "Hermes run failed"))
        return {"text": "".join(parts).strip(), "tools": tools, "run_id": run_id}

    def stop(self, run_id: str) -> dict:
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

    def do_POST(self) -> None:
        if not self._authorized():
            self._json(HTTPStatus.UNAUTHORIZED, {"error": "Nicht autorisiert"})
            return
        try:
            body = self._body()
            if self.path == "/chat":
                message = str(body.get("message") or "").strip()
                conversation = str(body.get("conversation") or "jarvis-apple").strip()
                if not message or len(message) > 20_000:
                    raise ValueError("Nachricht fehlt oder ist zu lang")
                if not conversation or len(conversation) > 80:
                    raise ValueError("Ungültige Unterhaltung")
                started = time.monotonic()
                result = self.client.chat(message, conversation)
                result["duration_ms"] = round((time.monotonic() - started) * 1000)
                self._json(HTTPStatus.OK, result)
                return
            if self.path == "/stop":
                run_id = str(body.get("run_id") or "").strip()
                if not run_id:
                    raise ValueError("run_id fehlt")
                self._json(HTTPStatus.OK, self.client.stop(run_id))
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
