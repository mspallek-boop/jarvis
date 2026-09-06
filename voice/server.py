#!/usr/bin/env python3
"""Private local neural speech worker. Model inference never contacts a provider."""
from __future__ import annotations

import argparse
import base64
import hmac
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

MAX_BODY = 8192
MAX_TEXT = 600
SAMPLE_RATE = 24000


def app_token(env_file: Path) -> str:
    token = os.environ.get('JARVIS_APP_TOKEN', '').strip()
    if not token and env_file.exists():
        for line in env_file.read_text().splitlines():
            key, sep, value = line.partition('=')
            if sep and key.strip() == 'JARVIS_APP_TOKEN':
                token = value.strip().strip('\"\'')
                break
    if len(token) < 24:
        raise ValueError('A valid JARVIS_APP_TOKEN is required')
    return token


def parse_text(body: bytes) -> str:
    try:
        payload = json.loads(body)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError('Invalid JSON') from exc
    if not isinstance(payload, dict) or not isinstance(payload.get('text'), str):
        raise ValueError('text must be a string')
    text = payload['text'].strip()
    if not text or len(text) > MAX_TEXT:
        raise ValueError('text must contain 1 to 600 characters')
    return text


class NeuralVoice:
    def __init__(self, model_path: Path):
        self.path = model_path.resolve()
        self.model = None

    def pcm(self, text):
        # Only installed library code and pinned local safetensors are loaded.
        os.environ['HF_HUB_OFFLINE'] = '1'
        os.environ['HF_HUB_DISABLE_IMPLICIT_TOKEN'] = '1'
        os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
        import mlx.core as mx
        import numpy as np
        from mlx_audio.tts.utils import load_model
        mx.set_cache_limit(128 * 1024 * 1024)
        mx.set_memory_limit(2 * 1024 * 1024 * 1024)
        if self.model is None:
            self.model = load_model(self.path, trust_remote_code=False)
        mx.random.seed(42)
        max_tokens = 750
        for result in self.model.generate_custom_voice(
            text=text, speaker='Aiden', language='German', temperature=0.7,
            max_tokens=max_tokens, stream=True, streaming_interval=0.5,
        ):
            samples = np.asarray(result.audio, dtype=np.float32).reshape(-1)
            if not np.isfinite(samples).all():
                raise ValueError('Invalid generated audio')
            if result.sample_rate != SAMPLE_RATE:
                raise ValueError('Unexpected sample rate')
            if result.token_count >= max_tokens:
                raise ValueError('Speech generation reached its limit')
            yield (np.clip(samples, -1, 1) * 32767).astype('<i2').tobytes()


class VoiceServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, token, engine):
        if address[0] != '127.0.0.1':
            raise ValueError('Voice worker must bind to 127.0.0.1')
        self.token = token
        self.engine = engine
        self.busy = threading.Lock()
        super().__init__(address, VoiceHandler)


class VoiceHandler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(15)

    def log_message(self, *args):
        # Never persist request paths, headers, input text, or generated audio.
        pass

    def authorized(self):
        value = self.headers.get('Authorization', '')
        supplied = value[7:].strip() if value.lower().startswith('bearer ') else ''
        return bool(supplied) and hmac.compare_digest(
            supplied.encode(), self.server.token.encode())

    def json_response(self, status, body):
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(payload)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        if not self.authorized():
            self.json_response(401, {'error': 'Unauthorized'})
        elif self.path == '/health':
            self.json_response(200, {'ok': True, 'engine': 'qwen3-local', 'voice': 'Aiden'})
        else:
            self.json_response(404, {'error': 'Not found'})

    def do_POST(self):
        if not self.authorized():
            self.json_response(401, {'error': 'Unauthorized'})
            return
        if self.path != '/speech':
            self.json_response(404, {'error': 'Not found'})
            return
        try:
            if self.headers.get('Transfer-Encoding'):
                raise ValueError('Transfer-Encoding is not supported')
            lengths = self.headers.get_all('Content-Length', [])
            if len(lengths) != 1 or not lengths[0].isascii() or not lengths[0].isdigit():
                raise ValueError('A single valid Content-Length is required')
            length = int(lengths[0])
            if length < 1 or length > MAX_BODY:
                raise ValueError('Invalid body size')
            body = self.rfile.read(length)
            if len(body) != length:
                raise ValueError('Incomplete body')
            text = parse_text(body)
        except (ValueError, OSError):
            self.json_response(400, {'error': 'Invalid speech request'})
            return
        if not self.server.busy.acquire(blocking=False):
            self.json_response(429, {'error': 'Speech engine busy'})
            return
        try:
            self.send_response(200)
            self.send_header('Content-Type', 'application/x-ndjson')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Connection', 'close')
            self.end_headers()
            self.close_connection = True
            try:
                total_bytes = 0
                for pcm in self.server.engine.pcm(text):
                    total_bytes += len(pcm)
                    if len(pcm) > 512_000 or total_bytes > SAMPLE_RATE * 2 * 60:
                        raise ValueError('Audio limit exceeded')
                    self.frame({'type': 'audio', 'sample_rate': SAMPLE_RATE,
                                'format': 'pcm_s16le', 'data': base64.b64encode(pcm).decode()})
                if not total_bytes:
                    raise ValueError('No audio')
                self.frame({'type': 'done'})
            except (BrokenPipeError, ConnectionResetError, TimeoutError):
                pass
            except Exception:
                # No exception text: model/library errors may contain input.
                try:
                    self.frame({'type': 'error', 'error': 'Speech generation failed'})
                except OSError:
                    pass
        finally:
            self.server.busy.release()

    def frame(self, value):
        self.wfile.write(json.dumps(value).encode() + b'\n')
        self.wfile.flush()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', required=True, type=Path)
    parser.add_argument('--port', type=int, default=8788)
    parser.add_argument('--env-file', type=Path, default=Path.home()/'.hermes/.env')
    args = parser.parse_args()
    if not (args.model/'config.json').is_file():
        parser.error('A downloaded local model directory is required')
    server = VoiceServer(('127.0.0.1', args.port), app_token(args.env_file), NeuralVoice(args.model))
    print('JARVIS local neural speech worker on loopback', flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
