import io
import json
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
