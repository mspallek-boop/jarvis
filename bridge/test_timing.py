"""Messmodus: timing events are opt-in, carry no text, and never break or slow a turn."""
import importlib.util
import io
import json
import stat
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import jarvis_bridge as bridge

TOKEN = 'timing-test-token-000000000000000'
REPORT = Path(__file__).resolve().parents[1] / 'scripts' / 'voice_timing_report.py'
SPEECH_CONFIG = SimpleNamespace(app_token=TOKEN, openai_key='k', openai_model='',
                                openai_instructions='')


@pytest.fixture
def timing(tmp_path, monkeypatch):
    flag, log = tmp_path / 'voice-timing-on', tmp_path / 'logs' / 'voice-timing.jsonl'
    monkeypatch.setattr(bridge, 'TIMING_FLAG', flag)
    monkeypatch.setattr(bridge, 'TIMING_LOG', log)
    monkeypatch.setattr(bridge, '_TIMING_HEALTHY', True)
    flag.touch()

    def read():
        bridge.flush_timing()
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
    yield SimpleNamespace(flag=flag, log=log, read=read)
    # Nothing queued by this test may land in the next test's log.
    bridge.flush_timing()


def post(path, payload, config=None, client=None, token=TOKEN):
    body = json.dumps(payload).encode()
    h = bridge.JarvisHandler.__new__(bridge.JarvisHandler)
    h.config = config or SimpleNamespace(app_token=TOKEN)
    h.client = client or Mock()
    h.rfile = io.BytesIO((f'POST {path} HTTP/1.1\r\nHost: localhost\r\nAuthorization: Bearer {token}\r\n'
                         f'Content-Length: {len(body)}\r\n\r\n').encode() + body)
    h.wfile = io.BytesIO()
    h.client_address = ('127.0.0.1', 1)
    h.log_message = lambda *args: None
    h.handle_one_request()
    headers, content = h.wfile.getvalue().split(b'\r\n\r\n', 1)
    return int(headers.split()[1]), content


def audio_frames():
    return iter([{'type': 'audio', 'sample_rate': 24000, 'format': 'pcm_s16le', 'data': 'AAAA'},
                 {'type': 'done'}])


def app_events(*names):
    return {'client_run_id': 'run-1', 'events': [{'event': n, 't_ms': i} for i, n in enumerate(names)]}


def test_nothing_is_written_while_the_flag_is_absent(timing):
    timing.flag.unlink()
    assert bridge.mark_timing('run-1', 'received') is False
    assert timing.read() == [] and not timing.log.exists()


def test_marking_never_touches_the_disk_on_the_calling_thread(timing, monkeypatch):
    # A slow or blocked disk must delay the log, never the turn or its audio.
    opened = Mock(side_effect=AssertionError('disk access on the request thread'))
    writer_open = bridge.os.open
    monkeypatch.setattr(bridge.os, 'open', lambda *a, **k: (
        writer_open(*a, **k) if bridge.threading.current_thread().name == 'timing-writer' else opened()))
    assert bridge.mark_timing('run-1', 'received') is True
    assert [r['event'] for r in timing.read()] == ['received']


def test_a_broken_log_path_never_breaks_the_turn_and_is_reported(timing, tmp_path, monkeypatch):
    monkeypatch.setattr(bridge, 'TIMING_LOG', tmp_path)   # a directory cannot be appended to
    bridge.mark_timing('run-1', 'received')
    bridge.flush_timing()
    assert bridge._TIMING_HEALTHY is False
    status, content = post('/timing', app_events('speech_end'))
    assert status == 200 and json.loads(content)['degraded'] is True


def test_log_is_private_and_bounded(timing, monkeypatch):
    monkeypatch.setattr(bridge, 'MAX_TIMING_LOG_BYTES', 400)
    for _ in range(20):
        bridge.mark_timing('run-1', 'text_segment_start')
    timing.read()
    assert timing.log.stat().st_size <= 400
    assert stat.S_IMODE(timing.log.stat().st_mode) == 0o600
    assert bridge._TIMING_HEALTHY is False


def test_an_existing_readable_log_is_made_private(timing):
    timing.log.parent.mkdir(parents=True)
    timing.log.write_text('')
    timing.log.chmod(0o644)
    bridge.mark_timing('run-1', 'received')
    timing.read()
    assert stat.S_IMODE(timing.log.stat().st_mode) == 0o600


def test_a_planted_symlink_is_never_followed(timing, tmp_path):
    elsewhere = tmp_path / 'elsewhere'
    timing.log.parent.mkdir(parents=True)
    timing.log.symlink_to(elsewhere)
    bridge.mark_timing('run-1', 'received')
    timing.flag.unlink()
    bridge.flush_timing()
    assert not elsewhere.exists()


def test_free_text_values_are_dropped(timing):
    bridge.mark_timing('run-1', 'tool_started', tool='web_search',
                       note='Schick Sofia: ich komme später')
    [record] = timing.read()
    assert record['tool'] == 'web_search' and 'note' not in record


def test_chat_turn_marks_every_seam_in_order_without_text(timing, monkeypatch):
    events = [('run.started', {'run_id': 'r1'}),
              ('assistant.delta', {'delta': 'Ich schaue nach. '}),
              ('tool.started', {'tool_name': 'web_search'}),
              ('tool.completed', {}),
              ('assistant.delta', {'delta': 'Morgen sonnig.'}),
              ('assistant.completed', {'content': 'Morgen sonnig.'})]
    client = bridge.HermesClient(SimpleNamespace(hermes_url='http://unit.test'))
    client._session_id = lambda *a, **k: 'test-session'
    client._headers = lambda *a: {}
    stream = io.BytesIO(b''.join(f'event: {e}\ndata: {json.dumps(d)}\n\n'.encode() for e, d in events))
    monkeypatch.setattr(bridge.urllib.request, 'urlopen', Mock(return_value=stream))
    client.chat('Wie wird das Wetter morgen?', 'test', 'run-1', on_event=lambda frame: None)
    assert [r['event'] for r in timing.read()] == [
        'lock_acquired', 'hermes_request', 'run_started', 'text_segment_start',
        'tool_started', 'tool_finished', 'text_segment_start',
        'assistant_completed', 'text_forwarded']
    raw = timing.log.read_text()
    assert not any(word in raw for word in ('Wetter', 'sonnig', 'schaue'))
    assert {r['run'] for r in timing.read()} == {'run-1'}


def test_stream_handler_marks_received_and_done(timing):
    client = Mock()
    client.chat.return_value = {'text': 'Hallo', 'tools': [{'name': 'web_search'}]}
    status, _ = post('/chat/stream', {'message': 'Hallo', 'conversation': 'test',
                                      'client_run_id': 'run-7'}, client=client)
    records = timing.read()
    assert status == 200
    assert [r['event'] for r in records] == ['received', 'done']
    assert records[1]['tools'] == 1


def test_speech_marks_first_audio_per_sentence(timing, monkeypatch):
    monkeypatch.setattr(bridge, '_openai_speech_frames', lambda *a, **k: audio_frames())
    status, _ = post('/speech', {'text': 'Morgen sonnig.', 'voice_id': 'openai:onyx',
                                 'client_run_id': 'run-1', 'seq': 2}, config=SPEECH_CONFIG)
    records = timing.read()
    assert status == 200
    assert [r['event'] for r in records] == ['tts_received', 'tts_first_audio', 'tts_done']
    assert all(r['seq'] == 2 for r in records) and records[1]['provider'] == 'openai'


def test_speech_without_correlation_is_unchanged(timing, monkeypatch):
    monkeypatch.setattr(bridge, '_openai_speech_frames', lambda *a, **k: audio_frames())
    status, _ = post('/speech', {'text': 'Hallo.', 'voice_id': 'openai:onyx'}, config=SPEECH_CONFIG)
    assert status == 200 and timing.read() == []


@pytest.mark.parametrize('extra', [
    {'client_run_id': '../x'}, {'client_run_id': False}, {'client_run_id': 0},
    {'client_run_id': []}, {'client_run_id': None}, {'client_run_id': ''},
    {'seq': -1}, {'seq': 'eins'}, {'seq': True}, {'seq': None}])
def test_speech_rejects_malformed_correlation(timing, monkeypatch, extra):
    speech = Mock()
    monkeypatch.setattr(bridge, '_openai_speech_frames', speech)
    status, _ = post('/speech', {'text': 'Hallo.', 'voice_id': 'openai:onyx', **extra},
                     config=SPEECH_CONFIG)
    assert status == 400
    speech.assert_not_called()


def test_app_events_are_stored_on_the_app_clock(timing):
    status, content = post('/timing', {'client_run_id': 'run-1', 'events': [
        {'event': 'speech_end', 't_ms': 1000.0},
        {'event': 'playback_started', 't_ms': 3400, 'seq': 0}]})
    assert status == 200
    assert json.loads(content) == {'ok': True, 'enabled': True, 'accepted': 2, 'degraded': False}
    assert [(r['src'], r['event'], r['t']) for r in timing.read()] == [
        ('app', 'speech_end', 1000.0), ('app', 'playback_started', 3400.0)]


def test_timing_endpoint_requires_the_app_token(timing):
    assert post('/timing', app_events('speech_end'), token='wrong')[0] == 401
    assert timing.read() == []


@pytest.mark.parametrize('payload', [
    {'client_run_id': 'run-1', 'events': []},
    {'client_run_id': 'run-1', 'events': [{'event': 'speech_end', 't_ms': 1}] * 65},
    {'client_run_id': '../run', 'events': [{'event': 'speech_end', 't_ms': 1}]},
    {'client_run_id': 'run-1', 'events': [{'event': 'Speech End', 't_ms': 1}]},
    {'client_run_id': 'run-1', 'events': [{'event': 'speech_end', 't_ms': float('nan')}]},
    {'client_run_id': 'run-1', 'events': [{'event': 'speech_end', 't_ms': True}]},
    {'client_run_id': 'run-1', 'events': [{'event': 'speech_end', 't_ms': 1, 'seq': None}]},
    {'client_run_id': 'run-1', 'events': [{'event': 'speech_end', 't_ms': 1},
                                          {'event': 'bad name', 't_ms': 2}]},
])
def test_invalid_app_events_are_refused_and_nothing_is_written(timing, payload):
    assert post('/timing', payload)[0] == 400
    assert timing.read() == []


def test_app_events_are_accepted_but_dropped_while_disabled(timing):
    timing.flag.unlink()
    status, content = post('/timing', app_events('speech_end'))
    assert status == 200
    assert json.loads(content) == {'ok': True, 'enabled': False, 'accepted': 0}
    assert timing.read() == []


def load_report():
    spec = importlib.util.spec_from_file_location('voice_timing_report', REPORT)
    module = importlib.util.module_from_spec(spec)
    # Dataclasses resolve their annotations through sys.modules.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_report_splits_tool_turns_and_never_mixes_clocks():
    report = load_report()

    def ev(run, src, event, at, **extra):
        return {'run': run, 'src': src, 'event': event, 't': at, **extra}
    runs = report.collect([
        ev('a', 'bridge', 'received', 0), ev('a', 'bridge', 'hermes_request', 10),
        ev('a', 'bridge', 'text_segment_start', 1210), ev('a', 'bridge', 'assistant_completed', 2990),
        ev('a', 'bridge', 'text_forwarded', 3000), ev('a', 'bridge', 'done', 3100),
        ev('a', 'app', 'speech_end', 50_000), ev('a', 'app', 'playback_started', 54_000),
        ev('b', 'bridge', 'received', 0), ev('b', 'bridge', 'hermes_request', 5),
        ev('b', 'bridge', 'text_segment_start', 900),
        ev('b', 'bridge', 'tool_started', 1000, tool='web_search'),
        ev('b', 'bridge', 'text_segment_start', 6000), ev('b', 'bridge', 'assistant_completed', 6990),
        ev('b', 'bridge', 'text_forwarded', 7000),
        ev('b', 'bridge', 'tts_received', 7200, seq=0), ev('b', 'bridge', 'tts_first_audio', 8000, seq=0),
        ev('b', 'bridge', 'tts_received', 7300, seq=1), ev('b', 'bridge', 'tts_first_audio', 7350, seq=1),
        # Narration, a tool, then the answer only in assistant.completed: no
        # text_forwarded, the text reaches the app with done.
        ev('c', 'bridge', 'received', 0), ev('c', 'bridge', 'text_segment_start', 100),
        ev('c', 'bridge', 'tool_started', 200), ev('c', 'bridge', 'assistant_completed', 900),
        ev('c', 'bridge', 'done', 950),
    ])
    assert runs['a'].tools == 0 and runs['b'].tools == 1
    spans = report.span_values(runs)
    assert spans['hermes_first_token'] == {'a': 1200, 'b': 895}
    assert spans['answer_segment_generation'] == {'a': 1780, 'b': 990}   # never the narration
    assert spans['received_to_answer_text'] == {'a': 3000, 'b': 7000, 'c': 950}
    assert spans['perceived_latency'] == {'a': 4000}                      # app clock only
    assert spans['tts_first_audio'] == {'b': 800}                         # first sentence only
