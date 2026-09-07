import io
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import jarvis_bridge as bridge

TOKEN = 'test-speech-bridge-token-00000000'


def call(payload, token=TOKEN):
    body = json.dumps(payload).encode()
    handler = bridge.JarvisHandler.__new__(bridge.JarvisHandler)
    handler.config = SimpleNamespace(app_token=TOKEN)
    handler.rfile = io.BytesIO((
        f'POST /speech HTTP/1.1\r\nHost: localhost\r\nAuthorization: Bearer {token}\r\n'
        f'Content-Length: {len(body)}\r\n\r\n').encode() + body)
    handler.wfile = io.BytesIO()
    handler.client_address = ('127.0.0.1', 1)
    handler.log_message = lambda *args: None
    handler.handle_one_request()
    headers, content = handler.wfile.getvalue().split(b'\r\n\r\n', 1)
    return int(headers.split(b' ', 2)[1]), content


def test_speech_auth_gate(monkeypatch):
    upstream = Mock()
    monkeypatch.setattr(bridge, '_open_neural_speech', upstream)
    assert call({'text': 'Hallo'}, token='wrong')[0] == 401
    upstream.assert_not_called()


@pytest.mark.parametrize('text', ['', 3, 'x'*601])
def test_invalid_speech_does_not_reach_worker(monkeypatch, text):
    upstream = Mock()
    monkeypatch.setattr(bridge, '_open_neural_speech', upstream)
    assert call({'text': text})[0] == 400
    upstream.assert_not_called()


def test_neural_worker_unavailable(monkeypatch):
    monkeypatch.setattr(bridge, '_open_neural_speech', Mock(side_effect=OSError('private detail')))
    status, content = call({'text': 'Hallo'})
    assert status == 503
    assert b'private detail' not in content


def test_stream_passed_without_buffering_or_hermes_key(monkeypatch):
    stream = b'{"type":"audio","data":"AAE="}\n{"type":"done"}\n'
    upstream = Mock(return_value=io.BytesIO(stream))
    monkeypatch.setattr(bridge, '_open_neural_speech', upstream)
    status, content = call({'text': ' Hallo '})
    assert status == 200
    assert content == stream
    upstream.assert_called_once_with('Hallo', TOKEN)


def eleven_config(**overrides):
    config = dict(app_token=TOKEN, hermes_key='hermes-key-value',
                  elevenlabs_key='eleven-key-value',
                  elevenlabs_voice_id='JBFqnCBsd6RMkjVDRZzb',
                  elevenlabs_model='eleven_multilingual_v2',
                  elevenlabs_stability=0.6, elevenlabs_similarity=0.8,
                  elevenlabs_style=0.0)
    config.update(overrides)
    return SimpleNamespace(**config)


def test_multilingual_model_omits_language_code():
    # ElevenLabs answers 400 when eleven_multilingual_v2 is sent a language_code.
    payload = bridge._elevenlabs_payload('Guten Abend, sir.', eleven_config())
    assert 'language_code' not in payload
    assert payload['model_id'] == 'eleven_multilingual_v2'
    assert payload['voice_settings']['stability'] == 0.6


def test_flash_model_keeps_language_code():
    payload = bridge._elevenlabs_payload('Guten Abend.',
                                         eleven_config(elevenlabs_model='eleven_flash_v2_5'))
    assert payload['language_code'] == 'de'


def test_credentials_never_become_spoken_text():
    config = eleven_config()
    payload = bridge._elevenlabs_payload(
        f'Der Schlüssel ist {config.elevenlabs_key} und {config.hermes_key}.', config)
    assert config.elevenlabs_key not in payload['text']
    assert config.hermes_key not in payload['text']
    assert TOKEN not in payload['text']


def test_missing_key_or_voice_is_refused_before_any_request():
    for broken in (eleven_config(elevenlabs_key=''),
                   eleven_config(elevenlabs_voice_id=''),
                   eleven_config(elevenlabs_voice_id='hat leerzeichen')):
        with pytest.raises(ValueError):
            bridge._open_elevenlabs_speech('Hallo', broken)


def test_malformed_numeric_env_falls_back(monkeypatch):
    monkeypatch.setenv('ELEVENLABS_STABILITY', 'sehr ruhig')
    assert bridge._env_float('ELEVENLABS_STABILITY', 0.6) == 0.6
    monkeypatch.setenv('ELEVENLABS_STABILITY', '5')
    assert bridge._env_float('ELEVENLABS_STABILITY', 0.6) == 1.0


CATALOGUE = [{'id': 'onwK4e9ZLuTAKqWW03F9', 'name': 'Daniel', 'accent': 'british',
              'gender': 'male', 'description': 'formal'},
             {'id': 'JBFqnCBsd6RMkjVDRZzb', 'name': 'George', 'accent': 'british',
              'gender': 'male', 'description': 'mature'}]


def test_client_may_only_choose_a_voice_the_account_offers(monkeypatch):
    # Otherwise the app could spend the user's provider quota on any id it liked.
    monkeypatch.setattr(bridge, 'elevenlabs_voices', lambda c, force=False: CATALOGUE)
    config = eleven_config()
    assert bridge.resolve_voice_id('JBFqnCBsd6RMkjVDRZzb', config) == 'JBFqnCBsd6RMkjVDRZzb'
    for rejected in ('cCwaxHZZF7rVaQK2aOys', 'nicht erlaubt', '../../etc/passwd'):
        with pytest.raises(ValueError):
            bridge.resolve_voice_id(rejected, config)


def test_no_choice_uses_the_configured_voice(monkeypatch):
    monkeypatch.setattr(bridge, 'elevenlabs_voices', lambda c, force=False: CATALOGUE)
    config = eleven_config()
    assert bridge.resolve_voice_id('', config) == config.elevenlabs_voice_id


def test_catalogue_outage_falls_back_instead_of_failing(monkeypatch):
    def boom(config, force=False):
        raise OSError('provider down')
    monkeypatch.setattr(bridge, 'elevenlabs_voices', boom)
    config = eleven_config()
    assert bridge.resolve_voice_id('JBFqnCBsd6RMkjVDRZzb', config) == config.elevenlabs_voice_id


def test_chosen_voice_reaches_the_request_url(monkeypatch):
    seen = {}

    class FakeOpener:
        def open(self, request, timeout=None):
            seen['url'] = request.full_url
            return io.BytesIO(b'')
    monkeypatch.setattr(bridge.urllib.request, 'build_opener', lambda *a: FakeOpener())
    bridge._open_elevenlabs_speech('Hallo', eleven_config(), 'JBFqnCBsd6RMkjVDRZzb')
    assert 'JBFqnCBsd6RMkjVDRZzb/stream' in seen['url']
    assert 'output_format=pcm_24000' in seen['url']


def test_catalogue_never_exposes_the_api_key(monkeypatch):
    raw = {'voices': [{'voice_id': 'onwK4e9ZLuTAKqWW03F9', 'name': 'Daniel',
                       'labels': {'accent': 'british', 'gender': 'male'}},
                      {'voice_id': 'zu kurz', 'name': 'Ungültig'}]}

    class FakeOpener:
        def open(self, request, timeout=None):
            assert request.headers.get('Xi-api-key') == 'eleven-key-value'
            return io.BytesIO(json.dumps(raw).encode())
    monkeypatch.setattr(bridge.urllib.request, 'build_opener', lambda *a: FakeOpener())
    voices = bridge._fetch_elevenlabs_voices(eleven_config())
    assert [v['id'] for v in voices] == ['onwK4e9ZLuTAKqWW03F9']
    assert 'eleven-key-value' not in json.dumps(voices)


def test_library_voice_on_a_free_plan_says_why(monkeypatch):
    # /voices lists library voices on every tier, but only paid plans may speak
    # with them. A bare "unavailable" would send the user debugging the wrong thing.
    monkeypatch.setattr(bridge, 'elevenlabs_voices', lambda c, force=False: CATALOGUE)
    monkeypatch.setattr(bridge, '_open_elevenlabs_speech', Mock(
        side_effect=bridge.urllib.error.HTTPError('u', 402, 'Payment Required', {}, None)))
    handler = bridge.JarvisHandler.__new__(bridge.JarvisHandler)
    handler.config = eleven_config(app_token=TOKEN, speech_provider='elevenlabs')
    sent = {}
    handler._json = lambda status, payload: sent.update(status=status, payload=payload)
    handler._handle_elevenlabs_speech('Hallo', 'JBFqnCBsd6RMkjVDRZzb')
    assert sent['status'] == 402
    assert 'bezahlten Tarif' in sent['payload']['error']


# --------------------------------------------------- ElevenLabs quota fallback

def call_full(payload, config_overrides=None):
    """Like call(), but with a realistic config and the raw response head."""
    config = SimpleNamespace(
        app_token=TOKEN, hermes_key='k', elevenlabs_key='e',
        speech_provider='elevenlabs', speech_fallback='macos', macos_voice='',
        elevenlabs_voice_id='abcdefghij', elevenlabs_model='eleven_flash_v2_5',
        elevenlabs_stability=0.6, elevenlabs_similarity=0.8, elevenlabs_style=0.0,
    )
    for key, value in (config_overrides or {}).items():
        setattr(config, key, value)
    body = json.dumps(payload).encode()
    handler = bridge.JarvisHandler.__new__(bridge.JarvisHandler)
    handler.config = config
    handler.rfile = io.BytesIO((
        f'POST /speech HTTP/1.1\r\nHost: localhost\r\nAuthorization: Bearer {TOKEN}\r\n'
        f'Content-Length: {len(body)}\r\n\r\n').encode() + body)
    handler.wfile = io.BytesIO()
    handler.client_address = ('127.0.0.1', 1)
    handler.log_message = lambda *args: None
    handler.handle_one_request()
    head, content = handler.wfile.getvalue().split(b'\r\n\r\n', 1)
    return int(head.split(b' ', 2)[1]), head, content


def _quota_exhausted(*args, **kwargs):
    raise bridge.urllib.error.HTTPError('https://api.elevenlabs.io', 401, 'quota_exceeded', {}, None)


def test_exhausted_elevenlabs_quota_speaks_with_the_local_voice(monkeypatch):
    monkeypatch.setattr(bridge, '_open_elevenlabs_speech', _quota_exhausted)
    status, head, content = call_full({'text': 'Systeme bereit.'})
    assert status == 200
    assert b'X-JARVIS-Speech-Provider: macos' in head
    frames = [json.loads(line) for line in content.splitlines() if line]
    assert frames[-1] == {'type': 'done'}
    audio = [f for f in frames if f['type'] == 'audio']
    assert audio and all(f['sample_rate'] == 24000 and f['format'] == 'pcm_s16le' for f in audio)


def test_fallback_can_be_switched_off(monkeypatch):
    monkeypatch.setattr(bridge, '_open_elevenlabs_speech', _quota_exhausted)
    status, _, content = call_full({'text': 'Hallo'}, {'speech_fallback': ''})
    assert status == 503
    assert b'Kontingent' in content


def test_no_say_binary_reports_the_provider_error(monkeypatch):
    monkeypatch.setattr(bridge, '_open_elevenlabs_speech', _quota_exhausted)
    monkeypatch.setattr(bridge.shutil, 'which', lambda name: None)
    assert call_full({'text': 'Hallo'})[0] == 503


def test_local_worker_outage_also_falls_back(monkeypatch):
    monkeypatch.setattr(bridge, '_open_neural_speech', Mock(side_effect=OSError('down')))
    status, head, _ = call_full({'text': 'Hallo'}, {'speech_provider': 'local'})
    assert status == 200
    assert b'X-JARVIS-Speech-Provider: macos' in head
