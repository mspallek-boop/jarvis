#!/usr/bin/env python3
"""Always-on Wake-on-LAN relay for a JARVIS Mac.

Run this on a Raspberry Pi, NAS, or Home Assistant host inside the Mac's LAN.
The iPhone reaches it over Tailscale. It can wake a sleeping Mac and proxy the
native app API without exposing a router port.
"""

from __future__ import annotations

import argparse
import hmac
import json
import os
import socket
import time
import urllib.error
import urllib.request
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse


MAX_BODY = 64 * 1024


def magic_packet(mac_address: str) -> bytes:
    compact = mac_address.replace(":", "").replace("-", "").strip()
    if len(compact) != 12:
        raise ValueError("MAC-Adresse muss 12 Hex-Zeichen enthalten")
    try:
        address = bytes.fromhex(compact)
    except ValueError as exc:
        raise ValueError("Ungültige MAC-Adresse") from exc
    return b"\xff" * 6 + address * 16


class RelayConfig:
    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        self.token = os.environ.get("JARVIS_APP_TOKEN", "").strip()
        self.mac_bridge = os.environ.get("JARVIS_MAC_BRIDGE_URL", "http://jarvis.local:8770").rstrip("/")
        self.mac_address = os.environ.get("JARVIS_MAC_ADDRESS", "").strip()
        self.broadcast = os.environ.get("JARVIS_MAC_BROADCAST", "255.255.255.255").strip()
        self.wake_port = int(os.environ.get("JARVIS_WAKE_PORT", "9"))
        self.wake_timeout = int(os.environ.get("JARVIS_WAKE_TIMEOUT", "90"))
        if len(self.token) < 24:
            raise SystemExit("JARVIS_APP_TOKEN must contain at least 24 characters")


class RelayHandler(BaseHTTPRequestHandler):
    config: RelayConfig

    def log_message(self, fmt: str, *args) -> None:
        print(f"{self.address_string()} - {fmt % args}")

    def _authorized(self) -> bool:
        value = self.headers.get("Authorization", "")
        supplied = value[7:].strip() if value.lower().startswith("bearer ") else ""
        return bool(supplied and hmac.compare_digest(self.config.token, supplied))

    def _json(self, status: int, body: dict) -> None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _mac_request(self, method: str, path: str, body: bytes | None = None, timeout: int = 310):
        request = urllib.request.Request(
            self.config.mac_bridge + path,
            data=body,
            method=method,
            headers={
                "Authorization": f"Bearer {self.config.token}",
                "Content-Type": self.headers.get("Content-Type", "application/json"),
                "Accept": self.headers.get("Accept", "application/json"),
            },
        )
        return urllib.request.urlopen(request, timeout=timeout)

    def _mac_online(self) -> bool:
        try:
            with self._mac_request("GET", "/health", timeout=3) as response:
                return response.status == HTTPStatus.OK
        except Exception:
            return False

    def _wake(self) -> None:
        if not self.config.mac_address:
            raise ValueError("JARVIS_MAC_ADDRESS ist nicht konfiguriert")
        packet = magic_packet(self.config.mac_address)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            for _ in range(3):
                sock.sendto(packet, (self.config.broadcast, self.config.wake_port))
                time.sleep(0.15)

    def _ensure_awake(self) -> bool:
        if self._mac_online():
            return True
        self._wake()
        deadline = time.monotonic() + self.config.wake_timeout
        while time.monotonic() < deadline:
            time.sleep(3)
            if self._mac_online():
                return True
        return False

    def _proxy(self, method: str, path: str, body: bytes | None = None) -> None:
        try:
            with self._mac_request(method, path, body) as response:
                data = response.read()
                self.send_response(response.status)
                self.send_header("Content-Type", response.headers.get("Content-Type", "application/json"))
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(data)
        except urllib.error.HTTPError as exc:
            self._json(HTTPStatus.BAD_GATEWAY, {"error": f"Mac-Bridge HTTP {exc.code}"})
        except Exception:
            self._json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "Mac ist nicht erreichbar"})

    def do_GET(self) -> None:
        if not self._authorized():
            self._json(HTTPStatus.UNAUTHORIZED, {"error": "Nicht autorisiert"})
            return
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            online = self._mac_online()
            self._json(HTTPStatus.OK, {"ok": True, "relay": "online", "mac": "online" if online else "sleeping_or_off"})
            return
        if parsed.path.startswith("/files"):
            if not self._ensure_awake():
                self._json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "Mac konnte nicht aufgeweckt werden"})
                return
            suffix = self.path
            self._proxy("GET", suffix)
            return
        self._json(HTTPStatus.NOT_FOUND, {"error": "Nicht gefunden"})

    def do_POST(self) -> None:
        if not self._authorized():
            self._json(HTTPStatus.UNAUTHORIZED, {"error": "Nicht autorisiert"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length > MAX_BODY:
            self._json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "Anfrage zu groß"})
            return
        body = self.rfile.read(length) if length else b"{}"
        if self.path == "/wake":
            try:
                self._wake()
                self._json(HTTPStatus.OK, {"ok": True, "message": "Wake-Signal wurde gesendet"})
            except ValueError as exc:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return
        if self.path in {"/chat", "/stop"}:
            try:
                if not self._ensure_awake():
                    self._json(HTTPStatus.SERVICE_UNAVAILABLE, {
                        "error": "Mac konnte nicht aufgeweckt werden. Er muss im Ruhezustand und mit Strom/WLAN verbunden sein."
                    })
                    return
            except ValueError as exc:
                self._json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": str(exc)})
                return
            self._proxy("POST", self.path, body)
            return
        self._json(HTTPStatus.NOT_FOUND, {"error": "Nicht gefunden"})


def main() -> None:
    parser = argparse.ArgumentParser(description="JARVIS always-on Wake-on-LAN relay")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()
    config = RelayConfig(args.host, args.port)
    handler = type("ConfiguredRelayHandler", (RelayHandler,), {"config": config})
    server = ThreadingHTTPServer((config.host, config.port), handler)
    print(f"JARVIS relay listening on {config.host}:{config.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
