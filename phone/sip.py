"""A small outbound SIP user agent: one call at a time, UDP, G.711.

Just enough of RFC 3261 for a consumer VoIP account behind home NAT:
REGISTER and INVITE with digest auth, rport (RFC 3581) so the proxy answers to
the NAT mapping it saw, CANCEL on ring timeout, BYE both ways, and RFC 4733
DTMF for phone menus.

Media is symmetric: RTP leaves from the socket that receives it, starting the
moment the far end sends SDP, so the provider's media relay latches onto our
NAT mapping. The A1 router maps ports per destination, which makes STUN-found
addresses wrong for SDP; they are deliberately not used.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import random
import re
import socket
import struct
from collections import deque
from dataclasses import dataclass
from typing import Callable, Optional

log = logging.getLogger("jarvis.phone.sip")

T1 = 0.5
USER_AGENT = "JARVIS-phone/1.0"
FRAME = 160  # 20 ms of 8 kHz G.711
SILENCE = {0: b"\xff", 8: b"\xd5"}
CODEC_NAMES = {0: "pcmu", 8: "pcma"}
COMPACT = {"v": "via", "f": "from", "t": "to", "i": "call-id", "m": "contact",
           "l": "content-length", "c": "content-type", "k": "supported"}
PHRASES = {200: "OK", 405: "Method Not Allowed", 481: "Call Does Not Exist", 486: "Busy Here"}
FAILURES = {
    404: "Die Nummer gibt es nicht.", 484: "Die Nummer ist unvollständig.",
    480: "Die Nummer ist gerade nicht erreichbar.", 486: "Besetzt.", 600: "Besetzt.",
    603: "Der Anruf wurde abgelehnt.", 487: "Niemand hat abgehoben.", 408: "Niemand hat abgehoben.",
    402: "Der Anbieter verweigert den Anruf (Guthaben?).", 403: "Der Anbieter verweigert den Anruf.",
    503: "Der Telefonanbieter ist gerade nicht verfügbar.",
}
DTMF_EVENTS = {**{str(d): d for d in range(10)}, "*": 10, "#": 11}


class SipError(Exception):
    pass


class CallFailed(Exception):
    def __init__(self, reason: str, code: int = 0):
        super().__init__(reason)
        self.reason = reason
        self.code = code


# --- messages ---------------------------------------------------------------

@dataclass
class SipMessage:
    first_line: str
    headers: list  # (lower-case name, value)
    body: bytes = b""

    @property
    def is_response(self) -> bool:
        return self.first_line.startswith("SIP/2.0")

    @property
    def status(self) -> int:
        return int(self.first_line.split(" ", 2)[1]) if self.is_response else 0

    @property
    def reason(self) -> str:
        parts = self.first_line.split(" ", 2)
        return parts[2] if self.is_response and len(parts) > 2 else ""

    @property
    def cseq(self) -> tuple:
        number, method = self.get("cseq").split()
        return int(number), method.upper()

    @property
    def method(self) -> str:
        return self.cseq[1] if self.is_response else self.first_line.split(" ", 1)[0].upper()

    def get(self, name: str, default: str = "") -> str:
        name = name.lower()
        for key, value in self.headers:
            if key == name:
                return value
        return default

    def get_all(self, name: str) -> list:
        name = name.lower()
        return [value for key, value in self.headers if key == name]


def parse_message(data: bytes) -> SipMessage:
    head, _, body = data.partition(b"\r\n\r\n")
    lines = head.decode("utf-8", "replace").split("\r\n")
    headers: list = []
    for line in lines[1:]:
        if line[:1] in (" ", "\t") and headers:
            key, value = headers[-1]
            headers[-1] = (key, value + " " + line.strip())
            continue
        key, sep, value = line.partition(":")
        if sep:
            key = key.strip().lower()
            headers.append((COMPACT.get(key, key), value.strip()))
    msg = SipMessage(lines[0].strip(), headers, body)
    length = msg.get("content-length")
    if length.isdigit():
        msg.body = body[: int(length)]
    return msg


def split_header_list(value: str) -> list:
    """Split a comma list such as Record-Route, ignoring commas inside <> or quotes."""
    items, current, depth, quoted = [], [], 0, False
    for ch in value:
        if ch == '"':
            quoted = not quoted
        elif not quoted and ch == "<":
            depth += 1
        elif not quoted and ch == ">":
            depth -= 1
        if ch == "," and depth == 0 and not quoted:
            items.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    tail = "".join(current).strip()
    return items + ([tail] if tail else [])


def header_param(value: str, name: str) -> Optional[str]:
    """';name=value' outside the <uri>; '' for a bare flag, None when absent."""
    outside = re.sub(r"<[^>]*>", "", value)
    m = re.search(r";\s*" + re.escape(name) + r"(?:=([^;,\s]*))?(?=[;,\s]|$)", outside, re.I)
    if not m:
        return None
    return m.group(1) if m.group(1) is not None else ""


def uri_of(value: str) -> str:
    m = re.search(r"<([^>]*)>", value)
    return m.group(1) if m else value.split(";", 1)[0].strip()


def parse_challenge(value: str) -> dict:
    _, _, rest = value.partition(" ")
    params = {}
    for m in re.finditer(r'(\w+)\s*=\s*(?:"([^"]*)"|([^,\s]+))', rest):
        params[m.group(1).lower()] = m.group(2) if m.group(2) is not None else m.group(3)
    return params


def _md5(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def digest_authorization(challenge: dict, method: str, uri: str, username: str,
                         password: str, cnonce: Optional[str] = None, nc: int = 1) -> str:
    algorithm = challenge.get("algorithm", "MD5")
    if algorithm.upper() != "MD5":
        raise SipError(f"Digest-Algorithmus {algorithm} wird nicht unterstützt.")
    realm, nonce = challenge.get("realm", ""), challenge.get("nonce", "")
    ha1 = _md5(f"{username}:{realm}:{password}")
    ha2 = _md5(f"{method}:{uri}")
    fields = [f'username="{username}"', f'realm="{realm}"', f'nonce="{nonce}"', f'uri="{uri}"']
    if "auth" in [q.strip() for q in challenge.get("qop", "").split(",")]:
        cnonce = cnonce or os.urandom(8).hex()
        count = f"{nc:08x}"
        response = _md5(f"{ha1}:{nonce}:{count}:{cnonce}:auth:{ha2}")
        fields += [f'response="{response}"', "algorithm=MD5", f'cnonce="{cnonce}"', "qop=auth", f"nc={count}"]
    else:
        fields += [f'response="{_md5(f"{ha1}:{nonce}:{ha2}")}"', "algorithm=MD5"]
    if "opaque" in challenge:
        fields.append(f'opaque="{challenge["opaque"]}"')
    return "Digest " + ", ".join(fields)


# --- SDP --------------------------------------------------------------------

def build_sdp(ip: str, port: int, session_id: int) -> bytes:
    return (
        "v=0\r\n"
        f"o=jarvis {session_id} {session_id} IN IP4 {ip}\r\n"
        "s=JARVIS\r\n"
        f"c=IN IP4 {ip}\r\n"
        "t=0 0\r\n"
        f"m=audio {port} RTP/AVP 0 8 101\r\n"
        "a=rtpmap:0 PCMU/8000\r\n"
        "a=rtpmap:8 PCMA/8000\r\n"
        "a=rtpmap:101 telephone-event/8000\r\n"
        "a=fmtp:101 0-15\r\n"
        "a=ptime:20\r\n"
        "a=sendrecv\r\n"
    ).encode()


def parse_sdp(body: bytes) -> dict:
    ip, port, payloads, dtmf = None, 0, [], None
    in_audio = False
    for line in body.decode("utf-8", "replace").splitlines():
        line = line.strip()
        if line.startswith("m="):
            parts = line[2:].split()
            in_audio = parts[0] == "audio"
            if in_audio:
                port = int(parts[1])
                payloads = [int(p) for p in parts[3:] if p.isdigit()]
        elif line.startswith("c=") and (in_audio or ip is None):
            ip = line.split()[-1]
        elif in_audio and line.lower().startswith("a=rtpmap:") and "telephone-event" in line.lower():
            dtmf = int(line[9:].split()[0])
    codec = next((p for p in payloads if p in (0, 8)), None)
    if not ip or not port or codec is None:
        raise SipError("Die Gegenstelle bietet keinen nutzbaren Ton an (G.711).")
    return {"ip": ip, "port": port, "codec": codec, "dtmf": dtmf}


# --- RTP --------------------------------------------------------------------

def rtp_packet(pt: int, seq: int, ts: int, ssrc: int, payload: bytes, marker: bool = False) -> bytes:
    return struct.pack("!BBHII", 0x80, (0x80 if marker else 0) | pt,
                       seq & 0xFFFF, ts & 0xFFFFFFFF, ssrc) + payload


def rtp_payload(data: bytes) -> Optional[tuple]:
    if len(data) < 12 or data[0] >> 6 != 2:
        return None
    offset = 12 + 4 * (data[0] & 0x0F)
    if data[0] & 0x10:
        if len(data) < offset + 4:
            return None
        offset += 4 + 4 * struct.unpack("!H", data[offset + 2:offset + 4])[0]
    end = len(data) - (data[-1] if data[0] & 0x20 else 0)
    if offset > end:
        return None
    return data[1] & 0x7F, data[offset:end]


def dtmf_payloads(digit: str) -> list:
    """RFC 4733 event packets for one 160 ms tone, three end packets included."""
    event = DTMF_EVENTS[digit]
    tone = [struct.pack("!BBH", event, 10, FRAME * i) for i in range(1, 9)]
    return tone + [struct.pack("!BBH", event, 0x80 | 10, FRAME * 8)] * 3


class RtpSession(asyncio.DatagramProtocol):
    """Sends a continuous 20 ms stream (audio or silence) and hands received audio on."""

    def __init__(self, on_audio: Callable[[bytes], None]):
        self.on_audio = on_audio
        self.transport = None
        self.remote = None
        self.pt = 8
        self.dtmf_pt = None
        self.receiving = False
        self.received = 0
        self.sent = 0
        self.ssrc = random.getrandbits(32)
        self.seq = random.getrandbits(16)
        self.ts = random.getrandbits(32)
        self._out: deque = deque()     # [item_id, bytearray]
        self._dtmf: deque = deque()    # (payload or None for a gap, first-of-digit)
        self._dtmf_ts = 0
        self._current = None           # item whose audio went out last
        self._current_sent = 0
        self._first = True
        self._task = None

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data, addr):
        parsed = rtp_payload(data)
        if parsed is None or self.remote is None or parsed[0] != self.pt:
            return
        self.received += 1
        if addr != self.remote:
            self.remote = addr  # symmetric relay: answer where the audio comes from
        if self.receiving:
            self.on_audio(parsed[1])

    def start(self, remote: tuple, pt: int, dtmf_pt: Optional[int]) -> None:
        self.remote, self.pt, self.dtmf_pt = remote, pt, dtmf_pt
        if self._task is None:
            self._task = asyncio.ensure_future(self._pump())

    def stop(self) -> None:
        if self._task:
            self._task.cancel()
            self._task = None
        if self.transport:
            self.transport.close()

    def play(self, item_id: str, audio: bytes) -> None:
        if self._out and self._out[-1][0] == item_id:
            self._out[-1][1].extend(audio)
        else:
            self._out.append([item_id, bytearray(audio)])

    def clear(self) -> Optional[tuple]:
        """Drop queued audio; return (item_id, ms actually played) of the cut item."""
        cut = None
        if self._out:
            head = self._out[0][0]
            cut = (head, self._current_sent // 8 if head == self._current else 0)
        self._out.clear()
        return cut

    @property
    def playing(self) -> bool:
        return bool(self._out)

    def send_dtmf(self, digits: str) -> str:
        sent = ""
        for digit in digits:
            if digit in DTMF_EVENTS and self.dtmf_pt is not None:
                packets = dtmf_payloads(digit)
                self._dtmf.append((packets[0], True))
                self._dtmf.extend((p, False) for p in packets[1:])
                self._dtmf.extend([(None, False)] * 5)  # 100 ms pause between digits
                sent += digit
        return sent

    async def _pump(self):
        loop = asyncio.get_running_loop()
        due = loop.time()
        while True:
            try:
                self._send_frame()
            except OSError as exc:
                log.warning("RTP send failed: %s", exc)
            due += 0.02
            delay = due - loop.time()
            if delay < -0.2:
                due = loop.time()  # fell far behind; resync instead of bursting
            await asyncio.sleep(max(0.0, delay))

    def _send_frame(self):
        if self.transport is None or self.remote is None:
            return
        if self._dtmf:
            payload, first = self._dtmf.popleft()
            if payload is not None:
                if first:
                    self._dtmf_ts = self.ts
                self.transport.sendto(rtp_packet(self.dtmf_pt, self.seq, self._dtmf_ts, self.ssrc,
                                                 payload, marker=first), self.remote)
                self.seq += 1
                self.ts += FRAME
                return
        frame = bytearray()
        while self._out and len(frame) < FRAME:
            item_id, buf = self._out[0]
            take = bytes(buf[:FRAME - len(frame)])
            del buf[:len(take)]
            if item_id != self._current:
                self._current, self._current_sent = item_id, 0
            self._current_sent += len(take)
            frame.extend(take)
            if not buf:
                self._out.popleft()
        frame.extend(SILENCE[self.pt] * (FRAME - len(frame)))
        self.transport.sendto(rtp_packet(self.pt, self.seq, self.ts, self.ssrc, bytes(frame),
                                         marker=self._first), self.remote)
        self.sent += 1
        self._first = False
        self.seq += 1
        self.ts += FRAME


# --- user agent -------------------------------------------------------------

@dataclass
class SipAccount:
    username: str
    password: str
    domain: str = "sip.fairytel.at"
    port: int = 5060
    auth_username: str = ""
    display_name: str = ""


def _branch() -> str:
    return "z9hG4bK" + os.urandom(8).hex()


def _tag() -> str:
    return os.urandom(6).hex()


def _local_ip_towards(ip: str) -> str:
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect((ip, 9))
        return probe.getsockname()[0]
    finally:
        probe.close()


class _ClientTx:
    """One request, retransmitted on T1 doubling until any response arrives."""

    def __init__(self, phone: "SipPhone", branch: str, method: str, data: bytes):
        self.phone, self.key, self.data = phone, (branch, method), data
        self.queue: asyncio.Queue = asyncio.Queue()
        self.answered = False
        phone._pending[self.key] = self
        phone._send(data)
        self._task = asyncio.ensure_future(self._retransmit())

    async def _retransmit(self):
        interval = T1
        for _ in range(7):
            await asyncio.sleep(interval)
            if self.answered:
                return
            self.phone._send(self.data)
            interval = min(interval * 2, 4.0)

    def deliver(self, msg: SipMessage) -> None:
        self.answered = True
        self.queue.put_nowait(msg)

    async def final(self, timeout: float) -> SipMessage:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while True:
            msg = await asyncio.wait_for(self.queue.get(), max(0.01, deadline - loop.time()))
            if msg.status >= 200:
                return msg

    def close(self) -> None:
        self._task.cancel()
        self.phone._pending.pop(self.key, None)


class SipPhone(asyncio.DatagramProtocol):
    """Signalling socket, registration and a single outbound dialog."""

    def __init__(self, account: SipAccount, on_audio: Callable[[bytes], None],
                 on_ringing: Optional[Callable[[], None]] = None):
        self.account = account
        self.on_ringing = on_ringing or (lambda: None)
        self.rtp = RtpSession(on_audio)
        self.transport = None
        self.proxy: tuple = ()
        self.local_ip = "0.0.0.0"
        self.contact_host = ""
        self.rtp_port = 0
        self._pending: dict = {}
        self._keepalive = None
        self._reg_call_id = f"{os.urandom(10).hex()}@jarvis"
        self._reg_tag = _tag()
        self._reg_cseq = 0
        self.registered = False
        # dialog
        self.call_id = ""
        self.from_tag = _tag()
        self.local_cseq = 0
        self.invite_cseq = 0
        self.invite_uri = ""
        self.to_header = ""
        self.remote_target = ""
        self.route_set: list = []
        self.sdp = b""
        self.codec = 8
        self.established = False
        self.ended = asyncio.Event()
        self.end_reason = ""

    # transport

    async def open(self) -> None:
        loop = asyncio.get_running_loop()
        infos = await loop.getaddrinfo(self.account.domain, self.account.port,
                                       family=socket.AF_INET, type=socket.SOCK_DGRAM)
        self.proxy = infos[0][4][:2]
        self.local_ip = _local_ip_towards(self.proxy[0])
        self.transport, _ = await loop.create_datagram_endpoint(lambda: self, local_addr=("0.0.0.0", 0))
        self.contact_host = f"{self.local_ip}:{self.transport.get_extra_info('sockname')[1]}"
        for _ in range(20):
            port = random.randrange(20000, 40000, 2)
            try:
                await loop.create_datagram_endpoint(lambda: self.rtp, local_addr=("0.0.0.0", port))
                self.rtp_port = port
                break
            except OSError:
                continue
        else:
            raise SipError("Kein freier RTP-Port.")
        self._keepalive = asyncio.ensure_future(self._keepalive_loop())

    def _send(self, data: bytes, addr: Optional[tuple] = None) -> None:
        if self.transport:
            self.transport.sendto(data, addr or self.proxy)

    async def _keepalive_loop(self):
        while True:
            await asyncio.sleep(15)
            self._send(b"\r\n\r\n")  # keeps the router's UDP mapping to the proxy open

    def datagram_received(self, data, addr):
        if not data.strip():
            return
        try:
            msg = parse_message(data)
            if msg.is_response:
                self._on_response(msg)
            else:
                self._on_request(msg, addr)
        except Exception:  # a malformed packet must never end a call
            log.exception("SIP packet ignored")

    def _on_response(self, msg: SipMessage) -> None:
        number, method = msg.cseq
        if (method == "INVITE" and 200 <= msg.status < 300 and self.established
                and number == self.invite_cseq and msg.get("call-id") == self.call_id):
            self._ack_2xx()  # our ACK got lost; the 200 is being retransmitted
            return
        tx = self._pending.get((header_param(msg.get("via"), "branch"), method))
        if tx:
            tx.deliver(msg)

    # message building

    def _from(self, tag: str) -> str:
        name = f'"{self.account.display_name}" ' if self.account.display_name else ""
        return f"{name}<sip:{self.account.username}@{self.account.domain}>;tag={tag}"

    def _contact(self) -> str:
        return f"<sip:{self.account.username}@{self.contact_host}>"

    def _request(self, method: str, uri: str, *, branch: str, call_id: str, from_tag: str,
                 to: str, cseq: int, cseq_method: str = "", extra=(), body: bytes = b"",
                 contact: bool = False) -> bytes:
        lines = [f"{method} {uri} SIP/2.0",
                 f"Via: SIP/2.0/UDP {self.contact_host};branch={branch};rport",
                 "Max-Forwards: 70",
                 f"From: {self._from(from_tag)}",
                 f"To: {to}",
                 f"Call-ID: {call_id}",
                 f"CSeq: {cseq} {cseq_method or method}"]
        if contact:
            lines.append(f"Contact: {self._contact()}")
        lines += [f"User-Agent: {USER_AGENT}", *extra, f"Content-Length: {len(body)}", "", ""]
        return "\r\n".join(lines).encode() + body

    def _authorization(self, resp: SipMessage, method: str, uri: str) -> str:
        proxy = resp.status == 407
        challenge = parse_challenge(resp.get("proxy-authenticate" if proxy else "www-authenticate"))
        value = digest_authorization(challenge, method, uri,
                                     self.account.auth_username or self.account.username,
                                     self.account.password)
        return f"{'Proxy-Authorization' if proxy else 'Authorization'}: {value}"

    def _learn_nat(self, resp: SipMessage) -> None:
        via = resp.get("via")
        received, rport = header_param(via, "received"), header_param(via, "rport")
        if received and rport and rport.isdigit():
            self.contact_host = f"{received}:{rport}"

    # registration

    async def register(self, expires: int = 300) -> None:
        uri = f"sip:{self.account.domain}"
        to = f"<sip:{self.account.username}@{self.account.domain}>"
        auth = None
        for attempt in range(2):
            self._reg_cseq += 1
            branch = _branch()
            extra = [f"Expires: {expires}"] + ([auth] if auth else [])
            data = self._request("REGISTER", uri, branch=branch, call_id=self._reg_call_id,
                                 from_tag=self._reg_tag, to=to, cseq=self._reg_cseq,
                                 extra=extra, contact=True)
            tx = _ClientTx(self, branch, "REGISTER", data)
            try:
                resp = await tx.final(32)
            except asyncio.TimeoutError:
                raise CallFailed("Der Telefonanbieter antwortet nicht.") from None
            finally:
                tx.close()
            self._learn_nat(resp)
            if resp.status in (401, 407) and attempt == 0:
                auth = self._authorization(resp, "REGISTER", uri)
                continue
            if 200 <= resp.status < 300:
                self.registered = expires > 0
                return
            if resp.status in (401, 403, 407):
                raise CallFailed("Fairytel lehnt die Anmeldung ab. Stimmen Benutzername und SIP-Passwort?",
                                 resp.status)
            raise CallFailed(f"Anmeldung beim Telefonanbieter fehlgeschlagen ({resp.status}).", resp.status)

    # outbound call

    async def dial(self, number: str, ring_timeout: float = 45.0) -> None:
        """Returns once the call is answered; raises CallFailed otherwise."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + ring_timeout
        self.call_id = f"{os.urandom(12).hex()}@jarvis"
        self.invite_uri = f"sip:{number}@{self.account.domain}"
        to = f"<{self.invite_uri}>"
        self.sdp = build_sdp(self.local_ip, self.rtp_port, random.randrange(1, 2 ** 31))
        auth = None
        for attempt in range(2):
            self.local_cseq += 1
            self.invite_cseq = self.local_cseq
            branch = _branch()
            extra = ["Allow: INVITE, ACK, CANCEL, BYE, OPTIONS, UPDATE, INFO",
                     "Content-Type: application/sdp"] + ([auth] if auth else [])
            data = self._request("INVITE", self.invite_uri, branch=branch, call_id=self.call_id,
                                 from_tag=self.from_tag, to=to, cseq=self.invite_cseq,
                                 extra=extra, body=self.sdp, contact=True)
            tx = _ClientTx(self, branch, "INVITE", data)
            try:
                resp = await self._invite_outcome(tx, branch, deadline)
            finally:
                tx.close()
            if 200 <= resp.status < 300:
                self._establish(resp)
                return
            self._ack_failure(resp, branch)
            if resp.status in (401, 407) and attempt == 0:
                auth = self._authorization(resp, "INVITE", self.invite_uri)
                continue
            raise CallFailed(FAILURES.get(resp.status, f"Der Anruf ging nicht durch ({resp.status}).")
                             , resp.status)

    async def _invite_outcome(self, tx: _ClientTx, branch: str, deadline: float) -> SipMessage:
        loop = asyncio.get_running_loop()
        while True:
            remaining = deadline - loop.time()
            try:
                if remaining <= 0:
                    raise asyncio.TimeoutError
                msg = await asyncio.wait_for(tx.queue.get(), remaining)
            except asyncio.TimeoutError:
                return await self._cancel(tx, branch)
            if msg.status >= 200:
                return msg
            if msg.status in (180, 183):
                self.on_ringing()
            if msg.body:
                self._start_media(msg)  # early media: opens the NAT path, audio stays gated

    async def _cancel(self, tx: _ClientTx, branch: str) -> SipMessage:
        if not tx.answered:
            raise CallFailed("Der Telefonanbieter antwortet nicht.")
        data = self._request("CANCEL", self.invite_uri, branch=branch, call_id=self.call_id,
                             from_tag=self.from_tag, to=f"<{self.invite_uri}>", cseq=self.invite_cseq)
        cancel = _ClientTx(self, branch, "CANCEL", data)
        try:
            await cancel.final(8)
        except asyncio.TimeoutError:
            pass
        finally:
            cancel.close()
        try:
            return await tx.final(5)
        except asyncio.TimeoutError:
            raise CallFailed("Niemand hat abgehoben.", 487) from None

    def _ack_failure(self, resp: SipMessage, branch: str) -> None:
        self._send("\r\n".join([
            f"ACK {self.invite_uri} SIP/2.0",
            f"Via: SIP/2.0/UDP {self.contact_host};branch={branch};rport",
            "Max-Forwards: 70",
            f"From: {self._from(self.from_tag)}",
            f"To: {resp.get('to')}",
            f"Call-ID: {self.call_id}",
            f"CSeq: {self.invite_cseq} ACK",
            "Content-Length: 0", "", ""]).encode())

    def _establish(self, resp: SipMessage) -> None:
        self.to_header = resp.get("to")
        self.remote_target = uri_of(resp.get("contact")) or self.invite_uri
        routes = []
        for value in resp.get_all("record-route"):
            routes.extend(split_header_list(value))
        self.route_set = list(reversed(routes))
        self.established = True
        self._ack_2xx()
        self._start_media(resp)
        self.rtp.receiving = True
        log.info("answered: codec %s, media %s, %d route(s)", CODEC_NAMES.get(self.codec),
                 self.rtp.remote, len(self.route_set))

    def _in_dialog(self, method: str, cseq: int, extra=()) -> bytes:
        lines = [f"{method} {self.remote_target} SIP/2.0",
                 f"Via: SIP/2.0/UDP {self.contact_host};branch={_branch()};rport",
                 "Max-Forwards: 70"]
        lines += [f"Route: {route}" for route in self.route_set]
        lines += [f"From: {self._from(self.from_tag)}", f"To: {self.to_header}",
                  f"Call-ID: {self.call_id}", f"CSeq: {cseq} {method}",
                  f"User-Agent: {USER_AGENT}", *extra, "Content-Length: 0", "", ""]
        return "\r\n".join(lines).encode()

    def _ack_2xx(self) -> None:
        self._send(self._in_dialog("ACK", self.invite_cseq))

    def _start_media(self, msg: SipMessage) -> None:
        if msg.get("content-type").lower().startswith("application/sdp") or msg.body.startswith(b"v=0"):
            media = parse_sdp(msg.body)
            self.codec = media["codec"]
            self.rtp.start((media["ip"], media["port"]), media["codec"], media["dtmf"])

    async def hangup(self) -> None:
        if not self.established or self.ended.is_set():
            self._end(self.end_reason or "aufgelegt")
            return
        extra: list = []
        for attempt in range(2):
            self.local_cseq += 1
            data = self._in_dialog("BYE", self.local_cseq, extra)
            branch = header_param(parse_message(data).get("via"), "branch")
            tx = _ClientTx(self, branch, "BYE", data)
            try:
                resp = await tx.final(8)
            except asyncio.TimeoutError:
                break
            finally:
                tx.close()
            if resp.status in (401, 407) and attempt == 0:
                extra = [self._authorization(resp, "BYE", self.remote_target)]
                continue
            break
        self._end("JARVIS hat aufgelegt")

    def _end(self, reason: str) -> None:
        if not self.ended.is_set():
            self.end_reason = reason
            self.established = False
            self.rtp.receiving = False
            self.ended.set()

    # requests from the other side

    def _on_request(self, msg: SipMessage, addr: tuple) -> None:
        method = msg.method
        in_dialog = bool(self.call_id) and msg.get("call-id") == self.call_id
        if method == "ACK":
            return
        if method == "BYE":
            self._respond(msg, 200 if in_dialog else 481, addr)
            if in_dialog:
                log.info("remote BYE (reason: %s); rtp in=%d out=%d", msg.get("reason") or "-",
                         self.rtp.received, self.rtp.sent)
                self._end("Das Gegenüber hat aufgelegt")
        elif method in ("INVITE", "UPDATE") and in_dialog:
            self._respond(msg, 200, addr, sdp=True)  # session refresh: same media
        elif method == "INVITE":
            self._respond(msg, 486, addr)  # someone calls the number while JARVIS is dialling
        elif method in ("OPTIONS", "INFO", "NOTIFY", "CANCEL"):
            self._respond(msg, 200, addr)
        else:
            self._respond(msg, 405, addr)

    def _respond(self, req: SipMessage, status: int, addr: tuple, sdp: bool = False) -> None:
        to = req.get("to")
        if header_param(to, "tag") is None:
            to += f";tag={self.from_tag}"
        body = self.sdp if sdp else b""
        lines = [f"SIP/2.0 {status} {PHRASES.get(status, 'OK')}"]
        lines += [f"Via: {via}" for via in req.get_all("via")]
        lines += [f"From: {req.get('from')}", f"To: {to}", f"Call-ID: {req.get('call-id')}",
                  f"CSeq: {req.get('cseq')}", f"User-Agent: {USER_AGENT}"]
        if sdp:
            lines += [f"Contact: {self._contact()}", "Content-Type: application/sdp"]
        lines += [f"Content-Length: {len(body)}", "", ""]
        self._send("\r\n".join(lines).encode() + body, addr)

    async def close(self) -> None:
        if self._keepalive:
            self._keepalive.cancel()
        self.rtp.stop()
        if self.registered:
            try:
                await self.register(expires=0)
            except Exception:
                log.warning("Abmelden beim Anbieter fehlgeschlagen")
        if self.transport:
            self.transport.close()
