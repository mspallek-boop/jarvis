import io
import json
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import jarvis_bridge as bridge

TOKEN = 'test-activity-token-000000000000'


def request(client, query='client_run_id=run-1', token=TOKEN):
    handler = bridge.JarvisHandler.__new__(bridge.JarvisHandler)
    handler.config = SimpleNamespace(app_token=TOKEN)
    handler.client = client
    handler.rfile = io.BytesIO((f'GET /activity?{query} HTTP/1.1\r\nHost: localhost\r\n'
                               f'Authorization: Bearer {token}\r\n\r\n').encode())
    handler.wfile = io.BytesIO()
    handler.client_address = ('127.0.0.1', 1)
    handler.log_message = lambda *args: None
    handler.handle_one_request()
    headers, body = handler.wfile.getvalue().split(b'\r\n\r\n', 1)
    return int(headers.split()[1]), json.loads(body)


def test_activity_auth_before_lookup():
    client = Mock()
    assert request(client, token='wrong')[0] == 401
    client.activity.assert_not_called()


@pytest.mark.parametrize('query', ['', 'client_run_id=../secret', 'client_run_id=a&client_run_id=b'])
def test_activity_rejects_bad_identifiers(query):
    client = Mock()
    assert request(client, query=query)[0] == 400
    client.activity.assert_not_called()


def test_activity_is_scoped_and_never_exposes_arguments_or_run_id():
    client = bridge.HermesClient(SimpleNamespace())
    client._client_runs['run-1'] = {'cancelled': False, 'run_id': 'private-hermes-id', 'input': 'private'}
    client._client_runs['run-2'] = {'cancelled': False, 'phase': 'queued'}
    client._set_activity('run-1', 'tool', 'web_search')
    assert request(client) == (200, {'phase': 'tool', 'tool': 'web_search'})
    assert client.activity('run-2') == {'phase': 'queued', 'tool': ''}
    client._client_runs['run-1']['cancelled'] = True
    assert client.activity('run-1')['phase'] == 'stopping'
    client._client_runs.pop('run-1')
    assert client.activity('run-1') == {'phase': 'unknown', 'tool': ''}


def test_tool_payload_cannot_become_status_text():
    client = bridge.HermesClient(SimpleNamespace())
    client._client_runs['run-1'] = {'cancelled': False}
    client._set_activity('run-1', 'tool', 'terminal token=private')
    assert client.activity('run-1') == {'phase': 'tool', 'tool': ''}
    client._set_activity('other', 'tool', 'web_search')
    assert 'other' not in client._client_runs


# ------------------------------------------------------------- the run board

def board(token=TOKEN, client=None):
    handler = bridge.JarvisHandler.__new__(bridge.JarvisHandler)
    handler.config = SimpleNamespace(app_token=TOKEN)
    handler.client = client or bridge.HermesClient(SimpleNamespace())
    handler.rfile = io.BytesIO(('GET /runs HTTP/1.1\r\nHost: localhost\r\n'
                               f'Authorization: Bearer {token}\r\n\r\n').encode())
    handler.wfile = io.BytesIO()
    handler.client_address = ('127.0.0.1', 1)
    handler.log_message = lambda *args: None
    handler.handle_one_request()
    headers, body = handler.wfile.getvalue().split(b'\r\n\r\n', 1)
    return int(headers.split()[1]), json.loads(body)


def test_run_board_needs_the_app_token():
    client = Mock()
    assert board(token='wrong', client=client)[0] == 401
    client.active_runs.assert_not_called()


def test_empty_run_board():
    assert board()[1] == {'runs': [], 'count': 0}


def test_run_board_lists_every_turn_longest_first():
    client = bridge.HermesClient(SimpleNamespace())
    client._client_runs = {
        'run-new': {'cancelled': False, 'phase': 'thinking', 'tool': '',
                    'conversation': 'b', 'started': 1_000_000_090.0},
        'run-old': {'cancelled': False, 'phase': 'tool', 'tool': 'web_search',
                    'conversation': 'a', 'started': 1_000_000_000.0},
    }
    bridge.time.time = lambda: 1_000_000_100.0
    try:
        status, body = board(client=client)
    finally:
        import importlib, time as real_time
        bridge.time.time = real_time.time
    assert status == 200
    assert body['count'] == 2
    assert [run['client_run_id'] for run in body['runs']] == ['run-old', 'run-new']
    assert body['runs'][0] == {'client_run_id': 'run-old', 'phase': 'tool', 'tool': 'web_search',
                               'conversation': 'a', 'seconds': 100.0}


def test_cancelled_turn_reports_stopping_on_the_board():
    client = bridge.HermesClient(SimpleNamespace())
    client._client_runs = {'run-1': {'cancelled': True, 'phase': 'tool', 'tool': 'x',
                                     'conversation': 'a', 'started': 0.0}}
    assert board(client=client)[1]['runs'][0]['phase'] == 'stopping'


def test_run_board_never_carries_prompt_or_answer_text():
    client = bridge.HermesClient(SimpleNamespace())
    client._client_runs = {'run-1': {'cancelled': False, 'phase': 'thinking', 'tool': '',
                                     'conversation': 'a', 'started': 0.0,
                                     'text': 'geheimer Prompt', 'answer': 'geheime Antwort'}}
    assert b'geheim' not in json.dumps(board(client=client)[1]).encode()


# ----------------------------------------------------------- notifications

def notify_request(method, path, payload=None, token=TOKEN):
    handler = bridge.JarvisHandler.__new__(bridge.JarvisHandler)
    handler.config = SimpleNamespace(app_token=TOKEN)
    handler.client = Mock()
    body = b'' if payload is None else json.dumps(payload).encode()
    head = (f'{method} {path} HTTP/1.1\r\nHost: localhost\r\n'
            f'Authorization: Bearer {token}\r\n')
    if payload is not None:
        head += f'Content-Length: {len(body)}\r\n'
    handler.rfile = io.BytesIO(head.encode() + b'\r\n' + body)
    handler.wfile = io.BytesIO()
    handler.client_address = ('127.0.0.1', 1)
    handler.log_message = lambda *args: None
    handler.handle_one_request()
    headers, out = handler.wfile.getvalue().split(b'\r\n\r\n', 1)
    return int(headers.split()[1]), json.loads(out)


@pytest.fixture(autouse=True)
def fresh_notifications(tmp_path, monkeypatch):
    monkeypatch.setattr(bridge, 'NOTIFICATIONS',
                        bridge.Notifications(tmp_path / 'notifications.json'))


def test_notifications_need_the_app_token():
    assert notify_request('POST', '/notify', {'kind': 'info', 'title': 'x'}, token='wrong')[0] == 401
    assert notify_request('GET', '/notifications', token='wrong')[0] == 401


def test_a_notification_is_posted_then_read_back():
    status, body = notify_request('POST', '/notify',
                                  {'kind': 'whatsapp_reply', 'title': 'Rici',
                                   'text': 'hat geantwortet'})
    assert status == 200 and body['unread'] == 1
    status, body = notify_request('GET', '/notifications')
    assert status == 200 and body['unread'] == 1
    assert body['notifications'][0]['title'] == 'Rici'
    assert body['notifications'][0]['kind'] == 'whatsapp_reply'


def test_since_returns_only_what_the_app_has_not_seen():
    notify_request('POST', '/notify', {'kind': 'info', 'title': 'erste'})
    first = notify_request('GET', '/notifications')[1]['latest']
    notify_request('POST', '/notify', {'kind': 'info', 'title': 'zweite'})
    body = notify_request('GET', f'/notifications?since={first}')[1]
    assert [n['title'] for n in body['notifications']] == ['zweite']


def test_marking_read_clears_the_count_and_is_idempotent():
    notify_request('POST', '/notify', {'kind': 'info', 'title': 'a'})
    latest = notify_request('GET', '/notifications')[1]['latest']
    assert notify_request('POST', '/notifications/read', {'through': latest})[1] == {
        'marked': 1, 'unread': 0}
    assert notify_request('POST', '/notifications/read', {'through': latest})[1]['marked'] == 0
    assert notify_request('GET', '/notifications?unread=1')[1]['notifications'] == []


def test_an_unknown_kind_is_refused():
    assert notify_request('POST', '/notify', {'kind': 'wat', 'title': 'x'})[0] == 400


def test_an_empty_title_is_refused():
    assert notify_request('POST', '/notify', {'kind': 'info', 'title': '   '})[0] == 400


def test_long_and_multiline_text_is_trimmed_to_one_clean_line():
    """A banner is one line; newlines from a tool must not break the layout."""
    notify_request('POST', '/notify', {'kind': 'info', 'title': 'a\nb   c',
                                       'text': 'x' * 500})
    item = notify_request('GET', '/notifications')[1]['notifications'][0]
    assert item['title'] == 'a b c'
    assert len(item['text']) == 200 and '\n' not in item['text']


def test_the_queue_is_bounded():
    for index in range(bridge.MAX_NOTIFICATIONS + 10):
        notify_request('POST', '/notify', {'kind': 'info', 'title': f'n{index}'})
    items = notify_request('GET', '/notifications')[1]['notifications']
    assert len(items) == bridge.MAX_NOTIFICATIONS
    assert items[-1]['title'] == f'n{bridge.MAX_NOTIFICATIONS + 9}'


def test_notifications_survive_a_bridge_restart(tmp_path):
    store = bridge.Notifications(tmp_path / 'n.json')
    store.add('whatsapp_reply', 'Rici', 'hat geantwortet')
    reopened = bridge.Notifications(tmp_path / 'n.json')
    assert [i['title'] for i in reopened.since(0)] == ['Rici']
    assert reopened.unread() == 1
    # Ids keep climbing, so a client's `since` cursor stays valid.
    assert reopened.add('info', 'zweite')['id'] == 2


def test_the_notification_file_stays_private(tmp_path):
    path = tmp_path / 'n.json'
    bridge.Notifications(path).add('info', 'Rici')
    assert path.stat().st_mode & 0o077 == 0


def test_a_bad_since_value_is_refused():
    assert notify_request('GET', '/notifications?since=abc')[0] == 400


# --------------------------------------------------------------- stand-ins

def write_standins(monkeypatch, tmp_path, standins):
    path = tmp_path / 'standin.json'
    path.write_text(json.dumps({'standins': standins}))
    monkeypatch.setattr(bridge, 'STANDIN_STATE', path)
    return path


def test_standins_need_the_app_token(monkeypatch, tmp_path):
    write_standins(monkeypatch, tmp_path, {})
    assert notify_request('GET', '/standins', token='wrong')[0] == 401


def test_a_running_standin_is_listed_with_its_end(monkeypatch, tmp_path):
    ends = time.time() + 3600
    write_standins(monkeypatch, tmp_path,
                   {'4917648090349': {'name': 'Marie', 'until': ends, 'announced': True}})
    status, body = notify_request('GET', '/standins')
    assert status == 200 and body['count'] == 1
    assert body['standins'][0]['name'] == 'Marie'
    assert body['standins'][0]['until'] == pytest.approx(ends)
    assert body['standins'][0]['announced'] is True


def test_the_contact_number_never_leaves_the_bridge(monkeypatch, tmp_path):
    """The app shows a name and a time; a number on the wire is personal data."""
    write_standins(monkeypatch, tmp_path,
                   {'4917648090349': {'name': 'Marie', 'until': time.time() + 60}})
    assert b'4917648090349' not in json.dumps(notify_request('GET', '/standins')[1]).encode()


def test_an_expired_standin_is_not_shown(monkeypatch, tmp_path):
    """A countdown that has already run out must not linger."""
    write_standins(monkeypatch, tmp_path,
                   {'4917648090349': {'name': 'Marie', 'until': time.time() - 1}})
    assert notify_request('GET', '/standins')[1] == {'standins': [], 'count': 0}


@pytest.mark.parametrize('content', ['', 'kaputt{', '[]', '{"standins": "nein"}'])
def test_an_unreadable_state_file_means_nothing_is_running(monkeypatch, tmp_path, content):
    """The file belongs to another service: half-written is not a 500."""
    path = tmp_path / 'standin.json'
    path.write_text(content)
    monkeypatch.setattr(bridge, 'STANDIN_STATE', path)
    assert notify_request('GET', '/standins') == (200, {'standins': [], 'count': 0})


def test_a_missing_state_file_means_nothing_is_running(monkeypatch, tmp_path):
    monkeypatch.setattr(bridge, 'STANDIN_STATE', tmp_path / 'weg.json')
    assert notify_request('GET', '/standins') == (200, {'standins': [], 'count': 0})


def test_a_standin_carries_what_has_happened_so_far(monkeypatch, tmp_path):
    """Opening a running stand-in has to show the run, not only the last nudge."""
    write_standins(monkeypatch, tmp_path, {'4917648090349': {
        'name': 'Marie', 'until': time.time() + 60, 'started': 100.0, 'exchanges': 3,
        'history': [{'at': 101.0, 'gist': 'fragt nach Samstag', 'urgent': False}]}})
    body = notify_request('GET', '/standins')[1]['standins'][0]
    assert body['exchanges'] == 3 and body['started'] == 100.0
    assert body['history'] == [{'at': 101.0, 'gist': 'fragt nach Samstag', 'urgent': False}]


def test_a_broken_history_does_not_break_the_listing(monkeypatch, tmp_path):
    write_standins(monkeypatch, tmp_path, {'4917648090349': {
        'name': 'Marie', 'until': time.time() + 60, 'history': 'nein', 'exchanges': 'viele'}})
    assert notify_request('GET', '/standins')[0] == 200
