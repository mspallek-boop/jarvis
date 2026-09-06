"""Offline transport/auth tests; no model load, network, or credentials."""
import base64
import io
import json
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from voice.server import VoiceHandler, parse_text

TOKEN = 'test-only-neural-voice-token-000000'


def request(method='POST', path='/speech', payload=None, authorization=TOKEN,
            length=None, extra_headers='', engine=None, lock=None):
    body = json.dumps(payload if payload is not None else {'text': 'Hallo.'}).encode()
    headers = f'{method} {path} HTTP/1.1\r\nHost: localhost\r\n'
    if authorization is not None:
        headers += f'Authorization: Bearer {authorization}\r\n'
    headers += f'Content-Length: {len(body) if length is None else length}\r\n'
    headers += extra_headers + '\r\n'
    handler = VoiceHandler.__new__(VoiceHandler)
    handler.rfile = io.BytesIO(headers.encode() + body)
    handler.wfile = io.BytesIO()
    handler.server = SimpleNamespace(token=TOKEN, engine=engine or Mock(pcm=Mock(return_value=[b'\x00\x01'])),
                                     busy=lock or threading.Lock())
    handler.close_connection = True
    handler.handle_one_request()
    output = handler.wfile.getvalue()
    head, content = output.split(b'\r\n\r\n', 1)
    status = int(head.split(b' ', 2)[1])
    return status, content, handler.server


@pytest.mark.parametrize('method,path', [('GET', '/health'), ('POST', '/speech')])
@pytest.mark.parametrize('token', [None, 'wrong'])
def test_auth_before_any_model_action(method, path, token):
    status, _, server = request(method, path, authorization=token)
    assert status == 401
    server.engine.pcm.assert_not_called()


def test_valid_audio_stream_has_explicit_completion():
    status, content, server = request()
    assert status == 200
    frames = [json.loads(line) for line in content.splitlines()]
    assert frames[0]['format'] == 'pcm_s16le'
    assert frames[0]['sample_rate'] == 24000
    assert base64.b64decode(frames[0]['data']) == b'\x00\x01'
    assert frames[-1] == {'type': 'done'}
    server.engine.pcm.assert_called_once_with('Hallo.')
    assert not server.busy.locked()


@pytest.mark.parametrize('length,extra', [('-1',''), ('0',''), ('9000',''),
                                         ('nope',''), ('2','Content-Length: 2\r\n'),
                                         ('2','Transfer-Encoding: chunked\r\n')])
def test_bad_framing_never_reaches_model(length, extra):
    status, _, server = request(length=length, extra_headers=extra)
    assert status == 400
    server.engine.pcm.assert_not_called()


@pytest.mark.parametrize('payload', [[], None, {'text': 1}, {'text': ''}, {'text': 'x'*601}])
def test_invalid_text(payload):
    with pytest.raises(ValueError):
        parse_text(json.dumps(payload).encode())


def test_busy_engine_rejects_without_queueing():
    lock = threading.Lock()
    lock.acquire()
    status, _, server = request(lock=lock)
    assert status == 429
    assert lock.locked()
    server.engine.pcm.assert_not_called()
    lock.release()


def test_model_failure_is_sanitized_and_unlocks():
    engine = Mock(pcm=Mock(side_effect=RuntimeError('private input must not leak')))
    status, content, server = request(engine=engine)
    assert status == 200  # HTTP stream has already begun; error is an explicit frame.
    assert json.loads(content)['type'] == 'error'
    assert b'private input' not in content
    assert not server.busy.locked()


def test_empty_audio_is_not_reported_as_success():
    status, content, server = request(engine=Mock(pcm=Mock(return_value=[])))
    assert status == 200
    assert json.loads(content)['type'] == 'error'
    assert not server.busy.locked()


def test_only_exact_speech_route_is_served():
    status, _, server = request(path='/speech/other')
    assert status == 404
    server.engine.pcm.assert_not_called()
