"""The phone module: SIP signalling, RTP, number policy and the realtime bridge.

Everything runs in-process: SIP and RTP go through a recording fake transport
and the realtime model is a scripted fake socket, so the suite stays offline.
"""

from __future__ import annotations

import asyncio
import base64
import json
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "phone"))

import call as phone  # noqa: E402
import policy  # noqa: E402
import sip  # noqa: E402

PROXY = ("198.51.100.1", 5060)


# --- helpers -----------------------------------------------------------------

class FakeTransport:
    def __init__(self):
        self.sent = []

    def sendto(self, data, addr=None):
        self.sent.append((data, addr))

    def close(self):
        pass


def make_phone(received=None):
    p = sip.SipPhone(sip.SipAccount("43720123456", "pw"),
                     on_audio=(received.append if received is not None else lambda _: None))
    p.transport = FakeTransport()
    p.proxy = PROXY
    p.local_ip = "192.168.1.20"
    p.contact_host = "192.168.1.20:5070"
    p.rtp_port = 30000
    p.rtp.transport = FakeTransport()
    return p


def last(p, prefix: bytes) -> bytes:
    for data, _ in reversed(p.transport.sent):
        if data.startswith(prefix):
            return data
    raise AssertionError(f"nothing sent starting with {prefix!r}")


def branch(data: bytes) -> str:
    return sip.header_param(sip.parse_message(data).get("via"), "branch")


def respond(p, request: bytes, status: int, reason: str, extra=(), body=b"", to_tag="srv"):
    req = sip.parse_message(request)
    via = req.get("via").replace(";rport", ";rport=40000") + ";received=203.0.113.7"
    to = req.get("to") + (f";tag={to_tag}" if status > 100 and to_tag else "")
    lines = [f"SIP/2.0 {status} {reason}", f"Via: {via}", f"From: {req.get('from')}", f"To: {to}",
             f"Call-ID: {req.get('call-id')}", f"CSeq: {req.get('cseq')}", *extra,
             f"Content-Length: {len(body)}", "", ""]
    p.datagram_received("\r\n".join(lines).encode() + body, PROXY)


async def settle():
    for _ in range(5):
        await asyncio.sleep(0)


ANSWER_SDP = (b"v=0\r\no=- 1 1 IN IP4 198.51.100.9\r\ns=-\r\nc=IN IP4 198.51.100.9\r\nt=0 0\r\n"
              b"m=audio 41000 RTP/AVP 8 101\r\na=rtpmap:8 PCMA/8000\r\n"
              b"a=rtpmap:101 telephone-event/8000\r\n")


# --- SIP primitives ------------------------------------------------------------

def test_digest_matches_rfc2617_example():
    challenge = sip.parse_challenge(
        'Digest realm="testrealm@host.com", qop="auth,auth-int", '
        'nonce="dcd98b7102dd2f0e8b11d0f600bfb0c093", opaque="5ccc069c403ebaf9f0171e9517f40e41"')
    header = sip.digest_authorization(challenge, "GET", "/dir/index.html", "Mufasa",
                                      "Circle Of Life", cnonce="0a4f113b")
    assert 'response="6629fae49393a05397450978507c4ef1"' in header
    assert "qop=auth" in header and "nc=00000001" in header
    assert 'opaque="5ccc069c403ebaf9f0171e9517f40e41"' in header


def test_digest_without_qop_and_unknown_algorithm():
    header = sip.digest_authorization({"realm": "r", "nonce": "n"}, "REGISTER", "sip:x", "u", "p")
    assert "qop" not in header and "cnonce" not in header
    with pytest.raises(sip.SipError):
        sip.digest_authorization({"realm": "r", "nonce": "n", "algorithm": "SHA-256"}, "INVITE", "sip:x", "u", "p")


def test_parse_message_compact_folded_and_length():
    raw = (b"SIP/2.0 200 OK\r\nv: SIP/2.0/UDP a;branch=z9hG4bK1\r\nf: <sip:a@b>;tag=1\r\n"
           b"Subject: one\r\n two\r\nCSeq: 7 INVITE\r\nl: 3\r\n\r\nabcEXTRA")
    msg = sip.parse_message(raw)
    assert msg.is_response and msg.status == 200 and msg.method == "INVITE"
    assert msg.get("via").endswith("z9hG4bK1") and msg.get("from") == "<sip:a@b>;tag=1"
    assert msg.get("subject") == "one two" and msg.body == b"abc"


def test_header_params_and_lists():
    assert sip.header_param("<sip:a@b;tag=uri>;tag=real", "tag") == "real"
    via = "SIP/2.0/UDP 10.0.0.2:5070;branch=z9hG4bKx;rport=40000;received=203.0.113.7"
    assert sip.header_param(via, "rport") == "40000"
    assert sip.header_param("SIP/2.0/UDP h;rport;branch=b", "rport") == ""
    assert sip.header_param("<sip:a@b>;tagx=1", "tag") is None
    assert sip.split_header_list('<sip:p1;lr>, "x, y" <sip:p2;lr>') == ["<sip:p1;lr>", '"x, y" <sip:p2;lr>']
    assert sip.uri_of("<sip:gw@198.51.100.9:5060>;expires=60") == "sip:gw@198.51.100.9:5060"


def test_sdp_offer_and_answer():
    offer = sip.build_sdp("192.168.1.20", 30000, 42).decode()
    assert "c=IN IP4 192.168.1.20" in offer and "m=audio 30000 RTP/AVP 0 8 101" in offer
    media = sip.parse_sdp(ANSWER_SDP)
    assert media == {"ip": "198.51.100.9", "port": 41000, "codec": 8, "dtmf": 101}
    with pytest.raises(sip.SipError):
        sip.parse_sdp(b"v=0\r\nc=IN IP4 1.2.3.4\r\nm=audio 4000 RTP/AVP 9\r\n")
    with pytest.raises(sip.SipError):
        sip.parse_sdp(b"v=0\r\nc=IN IP4 1.2.3.4\r\nm=audio 0 RTP/AVP 0\r\n")


def test_rtp_roundtrip_with_csrc_extension_and_padding():
    assert sip.rtp_payload(sip.rtp_packet(0, 1, 160, 5, b"abc")) == (0, b"abc")
    header = bytes([0x80 | 0x20 | 0x10 | 0x01, 8]) + b"\x00\x01" + b"\x00" * 8
    packet = header + b"CSRC" + b"\xbe\xde\x00\x01" + b"EXT!" + b"voice" + b"\x00\x00\x03"
    assert sip.rtp_payload(packet) == (8, b"voice")
    assert sip.rtp_payload(b"\x00" * 12) is None


def test_dtmf_event_packets():
    packets = sip.dtmf_payloads("5")
    assert len(packets) == 11
    assert packets[0][0] == 5 and packets[0][1] & 0x80 == 0
    assert all(p[1] & 0x80 for p in packets[-3:])
    assert int.from_bytes(packets[-1][2:], "big") == 1280


def test_rtp_session_plays_clears_and_dials_tones():
    rtp = sip.RtpSession(lambda _: None)
    rtp.transport = FakeTransport()
    rtp.remote, rtp.pt, rtp.dtmf_pt = ("198.51.100.9", 41000), 0, 101
    rtp.play("it1", b"\x01" * 400)
    rtp._send_frame()
    rtp._send_frame()
    assert rtp.clear() == ("it1", 40)  # two 20 ms frames of it1 actually went out
    assert not rtp.playing
    rtp._send_frame()
    assert sip.rtp_payload(rtp.transport.sent[-1][0])[1] == b"\xff" * 160  # silence keeps NAT open
    assert rtp.send_dtmf("1x#") == "1#"
    rtp._send_frame()
    pt, payload = sip.rtp_payload(rtp.transport.sent[-1][0])
    assert pt == 101 and payload[0] == 1


# --- SIP flows -------------------------------------------------------------------

def test_register_invite_with_auth_answer_and_remote_bye():
    received = []

    async def scenario():
        p = make_phone(received)
        reg = asyncio.ensure_future(p.register())
        await settle()
        first = last(p, b"REGISTER")
        respond(p, first, 401, "Unauthorized",
                extra=['WWW-Authenticate: Digest realm="sip.fairytel.at", nonce="n1", qop="auth"'])
        await settle()
        second = last(p, b"REGISTER")
        assert b"Authorization: Digest" in second and b'username="43720123456"' in second
        assert b"Contact: <sip:43720123456@203.0.113.7:40000>" in second  # NAT mapping learnt via rport
        respond(p, second, 200, "OK")
        await reg
        assert p.registered

        dial = asyncio.ensure_future(p.dial("06641234567"))
        await settle()
        invite = last(p, b"INVITE")
        assert invite.startswith(b"INVITE sip:06641234567@sip.fairytel.at SIP/2.0")
        respond(p, invite, 407, "Proxy Authentication Required",
                extra=['Proxy-Authenticate: Digest realm="sip.fairytel.at", nonce="n2"'])
        await settle()
        assert branch(last(p, b"ACK")) == branch(invite)
        invite2 = last(p, b"INVITE")
        assert b"Proxy-Authorization: Digest" in invite2
        assert sip.parse_message(invite2).cseq[0] == sip.parse_message(invite).cseq[0] + 1
        respond(p, invite2, 180, "Ringing")
        respond(p, invite2, 200, "OK", body=ANSWER_SDP, extra=[
            "Contact: <sip:gw@198.51.100.9:5060>", "Record-Route: <sip:198.51.100.1;lr>",
            "Content-Type: application/sdp"])
        await dial
        assert p.established and p.codec == 8 and p.rtp.remote == ("198.51.100.9", 41000)
        ack = last(p, b"ACK")
        assert ack.startswith(b"ACK sip:gw@198.51.100.9:5060 SIP/2.0")
        assert b"Route: <sip:198.51.100.1;lr>" in ack

        p.rtp.datagram_received(sip.rtp_packet(8, 1, 0, 9, b"\xd5" * 160), ("198.51.100.9", 41000))
        p.rtp.datagram_received(sip.rtp_packet(0, 2, 160, 9, b"\x00" * 160), ("198.51.100.9", 41000))
        assert received == [b"\xd5" * 160]  # wrong payload type is dropped

        call_id = sip.parse_message(invite2).get("call-id")
        bye = ("BYE sip:43720123456@203.0.113.7:40000 SIP/2.0\r\n"
               "Via: SIP/2.0/UDP 198.51.100.1;branch=z9hG4bKsrv\r\n"
               "From: <sip:06641234567@sip.fairytel.at>;tag=srv\r\n"
               f"To: <sip:43720123456@sip.fairytel.at>;tag={p.from_tag}\r\n"
               f"Call-ID: {call_id}\r\nCSeq: 1 BYE\r\nContent-Length: 0\r\n\r\n")
        p.datagram_received(bye.encode(), PROXY)
        assert p.ended.is_set() and "aufgelegt" in p.end_reason
        assert last(p, b"SIP/2.0 200").count(b"z9hG4bKsrv") == 1
        p.rtp.stop()

    asyncio.run(scenario())


def test_busy_is_reported_in_plain_words():
    async def scenario():
        p = make_phone()
        dial = asyncio.ensure_future(p.dial("06641234567"))
        await settle()
        respond(p, last(p, b"INVITE"), 486, "Busy Here")
        with pytest.raises(sip.CallFailed) as exc:
            await dial
        assert exc.value.reason == "Besetzt." and exc.value.code == 486
        assert last(p, b"ACK")

    asyncio.run(scenario())


def test_ring_timeout_cancels_the_invite():
    async def scenario():
        p = make_phone()
        dial = asyncio.ensure_future(p.dial("06641234567", ring_timeout=0.05))
        await settle()
        invite = last(p, b"INVITE")
        respond(p, invite, 180, "Ringing")
        await asyncio.sleep(0.1)
        cancel = last(p, b"CANCEL")
        assert branch(cancel) == branch(invite)
        respond(p, cancel, 200, "OK", to_tag="")
        respond(p, invite, 487, "Request Terminated")
        with pytest.raises(sip.CallFailed) as exc:
            await dial
        assert exc.value.code == 487

    asyncio.run(scenario())


# --- G.711 -------------------------------------------------------------------------

def test_alaw_mulaw_tables_preserve_the_signal():
    assert phone._ulaw_to_linear(0xFF) == 0 and phone.U2A[0xFF] == 0xD5
    for u in range(256):
        before = phone._ulaw_to_linear(u)
        after = phone._ulaw_to_linear(phone.A2U[phone.U2A[u]])
        assert abs(after - before) <= max(40, abs(before) * 0.07), (u, before, after)


# --- policy ------------------------------------------------------------------------

def test_numbers_are_normalized_and_dialled():
    assert policy.normalize("0664 / 123 45-67") == "+436641234567"
    assert policy.normalize("+49 (30) 1234567") == "+49301234567"
    assert policy.normalize("0049 30 1234567") == "+49301234567"
    assert policy.dial_string("+436641234567") == "06641234567"
    assert policy.dial_string("+49301234567") == "0049301234567"
    assert policy.dial_string("+436641234567", "e164") == "+436641234567"


@pytest.mark.parametrize("raw", ["112", "144", "0133", "0900 123456", "+49 900 1234567", "+49 700 12345678",
                                 "+1 212 555 1234", "0810 123 456", "664 1234567", "0664abc"])
def test_forbidden_numbers_are_refused(raw):
    with pytest.raises(policy.PolicyError):
        policy.check_number(policy.normalize(raw))


def test_daily_limit_counts_existing_calls(tmp_path, monkeypatch):
    monkeypatch.setattr(policy, "MAX_PER_DAY", 2)
    now = datetime(2026, 9, 11, 15, 0)
    for i, stamp in enumerate(["2026-09-11T09:00:00", "2026-09-10T09:00:00"]):
        (tmp_path / f"{i}.json").write_text(json.dumps({"created_at": stamp}))
    policy.check_limits(tmp_path, now)
    (tmp_path / "2.json").write_text(json.dumps({"created_at": "2026-09-11T10:00:00"}))
    with pytest.raises(policy.PolicyError):
        policy.check_limits(tmp_path, now)


# --- the call command and the realtime bridge -------------------------------------

@pytest.fixture()
def calls_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(phone, "CALLS", tmp_path / "calls")
    monkeypatch.setattr(phone, "ENV_FILE", tmp_path / "missing.env")
    for name in ("FAIRYTEL_SIP_USER", "FAIRYTEL_SIP_PASSWORD", "OPENAI_API_KEY"):
        monkeypatch.setenv(name, "test-value")
    spawned = []
    monkeypatch.setattr(phone.subprocess, "Popen", lambda argv, **kw: spawned.append(argv))
    return SimpleNamespace(path=tmp_path / "calls", spawned=spawned)


def start(tmp_path, capsys, to="0664 1234567"):
    task = tmp_path / "task.txt"
    task.write_text("Termin für Haarschnitt, Donnerstag nach 16 Uhr.")
    code = phone.main(["start", "--to", to, "--callee", "Friseur", "--task-file", str(task)])
    return code, json.loads(capsys.readouterr().out)


def test_start_records_and_spawns_one_call(calls_dir, tmp_path, capsys):
    code, result = start(tmp_path, capsys)
    assert code == 0 and result["ok"] and result["to"] == "+436641234567"
    record = json.loads((calls_dir.path / f"{result['call_id']}.json").read_text())
    assert record["status"] == "queued" and record["dial"] == "06641234567" and record["minutes"] == 6
    assert calls_dir.spawned[0][-3:] == ["run", "--id", result["call_id"]]

    code, second = start(tmp_path, capsys)
    assert code == 1 and "läuft schon" in second["error"]


def test_start_refuses_emergency_and_missing_credentials(calls_dir, tmp_path, capsys, monkeypatch):
    code, result = start(tmp_path, capsys, to="112")
    assert code == 1 and not calls_dir.spawned
    monkeypatch.delenv("FAIRYTEL_SIP_PASSWORD")
    code, result = start(tmp_path, capsys)
    assert code == 1 and "FAIRYTEL_SIP_PASSWORD" in result["error"] and "test-value" not in result["error"]


def test_instructions_disclose_ai_and_bound_the_task():
    text = phone.instructions("Nur Donnerstag.", "Marlon", "Friseur", 6)
    assert "KI-Assistent" in text and "im Auftrag von Marlon" in text
    assert text.rstrip().endswith("Nur Donnerstag.") and "höchstens 6 Minuten" in text


def test_instructions_answer_the_cost_question():
    """Called people often ask whether an AI's call costs them something."""
    text = phone.instructions("Nur Donnerstag.", "Marlon", "Friseur", 6)
    assert "Nein, für Sie kostet das nichts." in text
    assert "Nein, für dich kostet das nichts." in text


class FakeWS:
    def __init__(self, events):
        self.events, self.sent = events, []

    async def send(self, raw):
        self.sent.append(json.loads(raw))

    def __aiter__(self):
        return self._gen()

    async def _gen(self):
        for event in self.events:
            await asyncio.sleep(0)
            yield json.dumps(event)

    async def close(self):
        pass


def test_realtime_events_drive_the_call(calls_dir):
    record = {"id": "t1", "to": "+436641234567", "dial": "06641234567", "callee": "Friseur",
              "task": "x", "minutes": 6, "status": "in_call", "created_at": phone.now_iso()}
    events = [
        {"type": "response.output_audio.delta", "item_id": "it1",
         "delta": base64.b64encode(b"\xff" * 320).decode()},
        {"type": "input_audio_buffer.speech_started"},
        {"type": "conversation.item.input_audio_transcription.completed", "transcript": "Hallo?"},
        {"type": "response.output_audio_transcript.done", "transcript": "Guten Tag, hier spricht JARVIS."},
        {"type": "response.function_call_arguments.done", "name": "end_call", "call_id": "c1",
         "arguments": json.dumps({"outcome": "erledigt", "summary": "Donnerstag 17 Uhr fix."})},
        {"type": "response.done"},
    ]

    async def scenario():
        c = phone.PhoneCall(record, sip.SipAccount("u", "p"), "k")
        c.phone.codec = 8
        hung_up = []

        async def fake_hangup():
            hung_up.append(True)

        c.phone.hangup = fake_hangup
        c.ws = FakeWS(events)
        await c._read_realtime()
        await asyncio.gather(*c.tasks)
        return c, hung_up

    c, hung_up = asyncio.run(scenario())
    sent = c.ws.sent
    assert {"type": "conversation.item.truncate", "item_id": "it1", "content_index": 0, "audio_end_ms": 0} in sent
    assert sent[-1]["item"] == {"type": "function_call_output", "call_id": "c1", "output": '{"ok": true}'}
    assert not any(e["type"] == "response.create" for e in sent)
    assert hung_up == [True]
    saved = json.loads((calls_dir.path / "t1.json").read_text())
    assert saved["outcome"] == "erledigt" and saved["summary"] == "Donnerstag 17 Uhr fix."
    assert [t["who"] for t in saved["transcript"]] == ["gegenüber", "jarvis"]


def test_alaw_line_audio_reaches_the_model_as_mulaw(calls_dir):
    async def scenario():
        c = phone.PhoneCall({"id": "t2", "task": "x", "minutes": 6, "status": "in_call"},
                            sip.SipAccount("u", "p"), "k")
        c.phone.codec = 8
        c.ws = FakeWS([])
        c._on_audio(b"\xd5" * 160)
        c._on_audio(b"\x55" * 160)
        task = asyncio.ensure_future(c._forward_audio())
        await settle()
        task.cancel()
        return c.ws.sent

    sent = asyncio.run(scenario())
    assert len(sent) == 1 and sent[0]["type"] == "input_audio_buffer.append"
    assert base64.b64decode(sent[0]["audio"]) == (b"\xd5" * 160 + b"\x55" * 160).translate(phone.A2U)


def _finished(transcript):
    record = {"id": "t4", "task": "x", "minutes": 3, "status": "in_call",
              "answered_at": phone.now_iso(), "transcript": transcript}

    async def scenario():  # Python 3.9's asyncio.Event needs a running loop
        c = phone.PhoneCall(record, sip.SipAccount("u", "p"), "k")
        c._finish(status="done")
        return c.record

    return asyncio.run(scenario())


def test_empty_fairytel_balance_is_a_failure_not_a_call(calls_dir):
    record = _finished([{"who": "gegenüber", "at": "", "text": (
        "Ihr Konto weist kein ausreichendes Guthaben mehr auf. Bitte laden Sie es über den Onlineshop wieder auf.")}])
    assert record["status"] == "failed" and "Guthaben" in record["error"]
    assert "outcome" not in record


def test_call_cut_short_is_not_reported_as_partly_done(calls_dir):
    record = _finished([{"who": "gegenüber", "at": "", "text": "Hallo? Wer ist da?"}])
    assert record["status"] == "done" and record["outcome"] == "nicht_erledigt"
    assert "Hallo? Wer ist da?" in record["summary"]


def test_fatal_realtime_error_hangs_up(calls_dir):
    async def scenario():
        c = phone.PhoneCall({"id": "t3", "task": "x", "minutes": 6, "status": "in_call"},
                            sip.SipAccount("u", "p"), "k")
        hung_up = []

        async def fake_hangup():
            hung_up.append(True)

        c.phone.hangup = fake_hangup
        c.ws = FakeWS([{"type": "error", "error": {"code": "insufficient_quota", "message": "no credit"}}])
        await c._read_realtime()
        return c, hung_up

    c, hung_up = asyncio.run(scenario())
    assert hung_up == [True] and "insufficient_quota" in c.fatal
