import io
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import jarvis_bridge as bridge

TOKEN = 'stream-test-token-00000000000000'


def request(client, payload=None, token=TOKEN, path='/chat/stream'):
    body = json.dumps(payload if payload is not None else {
        'message': 'Hallo', 'conversation': 'test', 'client_run_id': 'run-1'}).encode()
    h = bridge.JarvisHandler.__new__(bridge.JarvisHandler)
    h.config = SimpleNamespace(app_token=TOKEN)
    h.client = client
    h.rfile = io.BytesIO((f'POST {path} HTTP/1.1\r\nHost: localhost\r\nAuthorization: Bearer {token}\r\n'
                         f'Content-Length: {len(body)}\r\n\r\n').encode() + body)
    h.wfile = io.BytesIO()
    h.client_address = ('127.0.0.1', 1)
    h.log_message = lambda *args: None
    client.output = h.wfile
    h.handle_one_request()
    headers, content = h.wfile.getvalue().split(b'\r\n\r\n', 1)
    return int(headers.split()[1]), headers, content


def test_auth_before_stream_or_backend():
    client = Mock()
    status, headers, body = request(client, token='wrong')
    assert status == 401
    assert b'ndjson' not in headers
    client.chat.assert_not_called()


@pytest.mark.parametrize('payload', [
    {'message': 'hello'},
    {'message': '', 'client_run_id': 'run-1'},
    {'message': 'hello', 'client_run_id': '../bad'},
])
def test_validation_before_stream(payload):
    client = Mock()
    assert request(client, payload)[0] == 400
    client.chat.assert_not_called()


def test_delta_is_visible_before_backend_finishes():
    client = Mock()
    def chat(message, conversation, client_run_id, on_event):
        on_event({'type': 'delta', 'text': 'Hallo. '})
        # This executes while the agent turn is still running.
        assert b'Hallo. ' in client.output.getvalue()
        assert b'"type": "done"' not in client.output.getvalue()
        return {'text': 'Hallo. Wie geht es?', 'tools': [], 'run_id': 'hermes-test'}
    client.chat.side_effect = chat
    status, headers, content = request(client)
    frames = [json.loads(line) for line in content.splitlines()]
    assert status == 200 and b'application/x-ndjson' in headers
    assert [f['type'] for f in frames] == ['activity', 'delta', 'done']
    assert frames[-1]['response']['text'] == 'Hallo. Wie geht es?'


def test_stream_error_does_not_leak_or_send_second_http_response():
    client = Mock()
    client.chat.side_effect = RuntimeError('private provider detail')
    status, _, content = request(client)
    assert status == 200
    assert json.loads(content.splitlines()[-1])['type'] == 'error'
    assert b'private' not in content and b'HTTP/' not in content


def test_legacy_chat_is_unchanged():
    client = Mock()
    client.chat.return_value = {'text': 'Hallo', 'tools': []}
    status, _, content = request(client, path='/chat')
    assert status == 200 and json.loads(content)['text'] == 'Hallo'
    client.chat.assert_called_once_with('Hallo', 'test', 'run-1')


def configured_client(monkeypatch, events):
    client = bridge.HermesClient(SimpleNamespace(hermes_url='http://unit.test'))
    client._session_id = lambda *a, **k: 'test-session'
    client._headers = lambda *a: {}
    stream = io.BytesIO(b''.join((f'event: {event}\ndata: {json.dumps(data)}\n\n').encode() for event, data in events))
    monkeypatch.setattr(bridge.urllib.request, 'urlopen', Mock(return_value=stream))
    return client


def test_hermes_deltas_pass_through_and_final_text_is_authoritative(monkeypatch):
    client = configured_client(monkeypatch, [
        ('assistant.delta', {'delta': 'Ein Satz. '}),
        ('assistant.delta', {'delta': 'Noch einer.'}),
        ('assistant.completed', {'content': 'Ein Satz. Noch einer.'}),
    ])
    frames = []
    result = client.chat('Hallo', 'test', 'run-1', on_event=frames.append)
    # Deltas are released once the segment is known to be the answer rather
    # than narration, so the text arrives whole and still equals the final.
    assert ''.join(f['text'] for f in frames if f['type'] == 'delta') == result['text']
    assert client.activity('run-1')['phase'] == 'unknown'


def test_disconnected_client_cancels_running_hermes_turn(monkeypatch):
    client = configured_client(monkeypatch, [
        ('run.started', {'run_id': 'hermes-test'}),
        ('assistant.delta', {'delta': 'Hallo.'}),
    ])
    client.stop = Mock()
    with pytest.raises(BrokenPipeError):
        client.chat('Hallo', 'test', 'run-1', on_event=Mock(side_effect=BrokenPipeError))
    client.stop.assert_called_once_with('hermes-test')
    assert client.activity('run-1')['phase'] == 'unknown'


def sse_run(events):
    """Drive HermesClient._chat_once over a scripted SSE stream."""
    import io
    from types import SimpleNamespace
    from unittest.mock import patch
    config = SimpleNamespace(hermes_url='http://127.0.0.1:8642', hermes_key='k',
                             app_token='t', session_key='s',
                             state_path=Path('/dev/null'))
    client = bridge.HermesClient.__new__(bridge.HermesClient)
    client.config = config
    client._client_runs = {}
    client._active_runs_lock = __import__('threading').Lock()
    client._session_id = lambda conversation, force_new=False: 'sess'
    client._headers = lambda accept='application/json': {}
    client._set_activity = lambda *a, **k: None
    client.activity = lambda rid: {'phase': 'tool', 'tool': 'terminal'}
    seen = []
    with patch.object(bridge.urllib.request, 'urlopen') as opener, \
         patch.object(bridge, 'parse_sse', lambda response: iter(events)):
        opener.return_value.__enter__.return_value = io.BytesIO(b'')
        result = client._chat_once('frage', 'conv', False, 'run-1',
                                   on_event=lambda f: seen.append(f))
    return result, seen


def test_thinking_before_a_tool_call_is_never_spoken():
    # The model narrates ("Lass mich die Dateien lesen") and then calls a tool.
    # Forwarding that text made JARVIS read minutes of reasoning aloud.
    result, seen = sse_run([
        ('run.started', {'run_id': 'r1'}),
        ('assistant.delta', {'delta': 'Ich sehe. Das ist ein größeres Swift-Projekt. '}),
        ('assistant.delta', {'delta': 'Lass mich die wichtigsten Dateien lesen.'}),
        ('tool.started', {'tool_name': 'terminal', 'preview': 'ls'}),
        ('tool.completed', {}),
        ('assistant.delta', {'delta': 'Es liegen neun Dateien dort.'}),
        ('assistant.completed', {'content': 'Es liegen neun Dateien dort.'}),
    ])
    spoken = [f['text'] for f in seen if f['type'] == 'delta']
    assert spoken == ['Es liegen neun Dateien dort.']
    assert 'Lass mich' not in ''.join(spoken)
    assert result['text'] == 'Es liegen neun Dateien dort.'
    # The short form still reaches the app: one activity frame when text
    # starts, one for the tool, one when the answer starts. That frame is also
    # what lets the bridge notice a client that has gone away.
    assert [f['type'] for f in seen] == ['activity', 'activity', 'activity', 'delta']


def test_narration_between_two_tools_is_dropped_too():
    result, seen = sse_run([
        ('run.started', {'run_id': 'r1'}),
        ('assistant.delta', {'delta': 'Zuerst schaue ich nach.'}),
        ('tool.started', {'tool_name': 'terminal', 'preview': 'ls'}),
        ('assistant.delta', {'delta': 'Jetzt verstehe ich die Architektur.'}),
        ('tool.started', {'tool_name': 'web_search', 'preview': 'q'}),
        ('assistant.delta', {'delta': 'Die Antwort lautet zwölf.'}),
        ('assistant.completed', {'content': 'Die Antwort lautet zwölf.'}),
    ])
    spoken = [f['text'] for f in seen if f['type'] == 'delta']
    assert spoken == ['Die Antwort lautet zwölf.']
    assert result['text'] == 'Die Antwort lautet zwölf.'


def test_answer_without_any_tool_still_reaches_the_app():
    result, seen = sse_run([
        ('run.started', {'run_id': 'r1'}),
        ('assistant.delta', {'delta': 'Guten Abend, '}),
        ('assistant.delta', {'delta': 'sir.'}),
        ('assistant.completed', {'content': 'Guten Abend, sir.'}),
    ])
    assert [f['text'] for f in seen if f['type'] == 'delta'] == ['Guten Abend, sir.']
    assert result['text'] == 'Guten Abend, sir.'


def test_attachments_are_classified_by_kind():
    found = bridge.extract_attachments(
        'Bild ![Katze](https://x.de/k.png), Video https://youtu.be/abc123, '
        'Quelle [Wikipedia](https://de.wikipedia.org/wiki/Katze), Clip https://x.de/a.MP4')
    assert [(a['kind'], a['title']) for a in found] == [
        ('image', 'Katze'), ('source', 'Wikipedia'), ('video', 'youtu.be'), ('video', 'x.de')]


def test_only_http_urls_become_attachments():
    # A data: or file: URL rendered by the app would reach into the device.
    text = ('file:///etc/passwd data:image/png;base64,AAAA javascript:alert(1) '
            'ftp://host/f.png https://ok.de/bild.png')
    found = bridge.extract_attachments(text)
    assert [a['url'] for a in found] == ['https://ok.de/bild.png']


def test_duplicate_links_appear_once_in_order():
    found = bridge.extract_attachments(
        'https://a.de/1.png und nochmal https://a.de/1.png und https://b.de/2.png')
    assert [a['url'] for a in found] == ['https://a.de/1.png', 'https://b.de/2.png']


def test_attachment_count_is_bounded():
    text = ' '.join(f'https://host{n}.de/x{n}.png' for n in range(40))
    assert len(bridge.extract_attachments(text)) == bridge.MAX_ATTACHMENTS


def test_trailing_punctuation_is_not_part_of_the_url():
    found = bridge.extract_attachments('Siehe https://example.com/seite.')
    assert found[0]['url'] == 'https://example.com/seite'


def test_answer_without_links_has_no_attachments():
    assert bridge.extract_attachments('Guten Abend, sir.') == []
    assert bridge.extract_attachments('') == []


def test_pasted_image_is_recognised_by_content_not_by_name(tmp_path, monkeypatch):
    import base64 as b64
    monkeypatch.setattr(bridge, 'UPLOAD_DIR', tmp_path / 'uploads')
    png = b64.b64encode(b'\x89PNG\r\n\x1a\n' + b'0' * 40).decode()
    stored = bridge.store_upload(png)
    assert stored.suffix == '.png' and stored.exists()
    assert stored.parent == tmp_path / 'uploads'
    # A script is refused however it is labelled.
    for rejected in (b64.b64encode(b'#!/bin/sh\nrm -rf /').decode(), '', 'nicht base64!!'):
        with pytest.raises(ValueError):
            bridge.store_upload(rejected)


def test_oversized_upload_is_refused(monkeypatch, tmp_path):
    import base64 as b64
    monkeypatch.setattr(bridge, 'UPLOAD_DIR', tmp_path / 'uploads')
    huge = b64.b64encode(b'\x89PNG\r\n\x1a\n' + b'0' * (bridge.MAX_UPLOAD_BYTES + 1)).decode()
    with pytest.raises(ValueError):
        bridge.store_upload(huge)


def test_only_uploaded_images_can_be_pointed_at(tmp_path, monkeypatch):
    import base64 as b64
    monkeypatch.setattr(bridge, 'UPLOAD_DIR', tmp_path / 'uploads')
    stored = bridge.store_upload(b64.b64encode(b'\x89PNG\r\n\x1a\n' + b'0' * 40).decode())
    augmented = bridge.message_with_image('Was ist das?', str(stored))
    assert 'vision_analyze' in augmented and augmented.endswith('Was ist das?')
    # An arbitrary path would turn the agent into a file reader for any client.
    outside = tmp_path / 'geheim.png'
    outside.write_bytes(b'\x89PNG\r\n\x1a\n')
    for rejected in (str(outside), '/etc/passwd', str(Path.home() / '.hermes/.env')):
        with pytest.raises(ValueError):
            bridge.message_with_image('Was ist das?', rejected)


def test_message_without_image_is_untouched():
    assert bridge.message_with_image('Guten Abend.', '') == 'Guten Abend.'
