"""Receivers for Stop-and-Wait / Go-Back-N / Selective Repeat.

The sender announces the protocol, window and sequence-number size in its
SYN, so one ``Receiver`` serves any of the three.

Go-Back-N / Stop-and-Wait receiver (window 1)
    accept only the packet with seq == expected; discard anything else;
    always reply with a cumulative ACK "next expected = expected".

Selective Repeat receiver (window N)
    accept any packet in [rcv_base, rcv_base + N), buffer it, deliver the
    in-order prefix to the application, ACK each packet individually.
    Packets in [rcv_base - N, rcv_base) are old duplicates whose ACK was
    lost: ACK them again, otherwise the sender would retransmit forever.

Flow control: every ACK advertises the free buffer space (``window``).

Connection state machine:

    LISTEN --SYN/send SYN-ACK--> SYN_RCVD --ACK or DATA--> ESTABLISHED
           --FIN/verify sha256, send FIN-ACK--> TIME_WAIT --(linger)--> CLOSED

TIME_WAIT keeps answering retransmitted FINs in case our FIN-ACK was lost.
"""

from __future__ import annotations

import hashlib
import json
import os
import select
import time
from dataclasses import dataclass
from typing import Callable, Optional

from .channel import ImpairedSocket
from .log import EventLog
from .packet import ACK, DATA, FIN, RST, SYN, CorruptPacket, Packet
from .stats import ReceiveResult, ReceiverStats

LISTEN, SYN_RCVD, ESTABLISHED, TIME_WAIT = "LISTEN", "SYN_RCVD", "ESTABLISHED", "TIME_WAIT"


@dataclass
class ReceiverConfig:
    out_dir: str = "received"
    linger: float = 3.0  # TIME_WAIT duration in seconds
    idle_timeout: float = 30.0  # abort a session silent for this long
    max_window: int = 1024  # refuse SYNs asking for more buffering than this


def _safe_name(name: str) -> str:
    """Never trust a file name that came over the network (path traversal)."""
    name = os.path.basename(str(name).replace("\\", "/")).strip() or "received.bin"
    if name in (".", ".."):
        name = "received.bin"
    return name


def _unique_path(directory: str, name: str) -> str:
    base, ext = os.path.splitext(name)
    path, k = os.path.join(directory, name), 1
    while os.path.exists(path):
        path = os.path.join(directory, f"{base} ({k}){ext}")
        k += 1
    return path


class _Session:
    def __init__(self, pkt: Packet, addr, meta: dict, out_dir: str):
        self.conn_id = pkt.conn_id
        self.peer = addr
        self.meta = meta
        self.protocol = meta.get("protocol", "gbn")
        self.window = int(meta.get("window", 1))
        self.seq_bits = int(meta.get("seq_bits", 32))
        self.M = 1 << self.seq_bits
        self.checksum = meta.get("checksum", "crc32")
        self.total_packets = int(meta.get("packets", 0))
        self.size = int(meta.get("size", 0))
        self.name = _safe_name(meta.get("name", "received.bin"))
        self.state = SYN_RCVD
        self.start = time.monotonic()
        self.last_heard = self.start
        self.expected = 0  # next in-order index (GBN) / rcv_base (SR)
        self.buffer: dict[int, bytes] = {}
        self.sha = hashlib.sha256()
        self.received_bytes = 0
        os.makedirs(out_dir, exist_ok=True)
        self.out_dir = out_dir
        self.tmp_path = _unique_path(out_dir, self.name + ".part")
        self.file = open(self.tmp_path, "wb")
        self.result: Optional[ReceiveResult] = None
        self.fin_reply: Optional[bytes] = None
        self.time_wait_until = 0.0

    def deliver(self, payload: bytes) -> None:
        self.file.write(payload)
        self.sha.update(payload)
        self.received_bytes += len(payload)
        self.expected += 1

    def rwnd(self) -> int:
        if self.protocol == "sr":
            return max(1, self.window - len(self.buffer))
        return max(1, self.window)


class Receiver:
    def __init__(self, sock: ImpairedSocket, cfg: Optional[ReceiverConfig] = None,
                 log: Optional[EventLog] = None, on_event: Optional[Callable[[dict], None]] = None):
        self.sock = sock
        self.cfg = cfg or ReceiverConfig()
        self.log = log or EventLog(False)
        self.stats = ReceiverStats()
        self._raw = sock.sock
        self._raw.setblocking(False)
        self.session: Optional[_Session] = None
        self._stop = False
        self.on_event = on_event
        self.on_deliver: Optional[Callable[[int, bytes], None]] = None  # (index, payload) hook

    def _deliver(self, s: "_Session", payload: bytes) -> None:
        idx = s.expected
        s.deliver(payload)
        if self.on_deliver is not None:
            self.on_deliver(idx, payload)

    def _emit(self, kind: str, **fields) -> None:
        if self.on_event is not None:
            fields["type"] = kind
            fields["src"] = "R"
            self.on_event(fields)

    def stop(self) -> None:
        """Ask serve_one() to return (ends TIME_WAIT early)."""
        self._stop = True

    # ------------------------------------------------------------------ API

    def serve_one(self, timeout: Optional[float] = None) -> Optional[ReceiveResult]:
        """Receive exactly one file. Returns None if nobody connects in time."""
        self.stats = ReceiverStats()
        self.session = None
        listen_deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            now = time.monotonic()
            s = self.session
            if s is None and listen_deadline is not None and now > listen_deadline:
                return None
            if self._stop:
                if s is not None and s.result is not None:
                    return s.result
                return self._abort("stopped") if s is not None else None
            if s is not None:
                if s.state == TIME_WAIT and now >= s.time_wait_until:
                    return s.result
                if s.state != TIME_WAIT and now - s.last_heard > self.cfg.idle_timeout:
                    return self._abort("sender went silent (idle timeout)")
            for raw, addr in self._recv(0.1):
                self._handle(raw, addr)

    def serve_forever(self):
        while True:
            yield self.serve_one()

    # ------------------------------------------------------------ internals

    def _recv(self, timeout: float):
        try:
            ready, _, _ = select.select([self._raw], [], [], timeout)
        except InterruptedError:
            return []
        out = []
        if not ready:
            return out
        while True:
            try:
                out.append(self._raw.recvfrom(65535))
            except (BlockingIOError, InterruptedError):
                break
            except OSError:
                break
        return out

    def _send(self, pkt: Packet, addr, checksum: str) -> None:
        self.sock.sendto(pkt.encode(checksum), addr)

    def _handle(self, raw: bytes, addr) -> None:
        self.stats.packets_received += 1
        try:
            pkt = Packet.decode(raw)
        except CorruptPacket as e:
            self.stats.corrupt_dropped += 1
            self.log("BADCRC", f"frame from {addr[0]}:{addr[1]} failed check ({e}) -> dropped")
            self._emit("rx_corrupt")
            return
        s = self.session

        if s is None:
            if pkt.flags & SYN and not pkt.flags & ACK:
                self._on_syn(pkt, addr)
            return

        if pkt.conn_id != s.conn_id or addr != s.peer:
            if pkt.flags & SYN and not pkt.flags & ACK:  # someone else tries to connect
                busy = Packet(SYN | ACK, conn_id=pkt.conn_id,
                              payload=json.dumps({"accept": False, "reason": "receiver busy"}).encode())
                self._send(busy, addr, "crc32")
            return

        s.last_heard = time.monotonic()
        if pkt.flags & SYN:  # our SYN-ACK was lost
            self._send_synack(s)
        elif pkt.flags & DATA:
            if s.state == SYN_RCVD:
                s.state = ESTABLISHED
            if s.state == ESTABLISHED:
                self._on_data(s, pkt)
            else:  # TIME_WAIT: late duplicate, just re-ACK
                self._ack(s, pkt.seq)
        elif pkt.flags & FIN:
            self._on_fin(s, pkt)
        elif pkt.flags & ACK and s.state == SYN_RCVD:
            s.state = ESTABLISHED
            self.log("INFO", "handshake ACK received -> ESTABLISHED")

    def _on_syn(self, pkt: Packet, addr) -> None:
        try:
            meta = json.loads(pkt.payload or b"{}")
        except ValueError:
            meta = {}
        reason = None
        if meta.get("protocol") not in ("sw", "gbn", "sr"):
            reason = "unknown protocol"
        elif not 1 <= int(meta.get("window", 1)) <= self.cfg.max_window:
            reason = "window too large"
        if reason:
            self._send(Packet(SYN | ACK, conn_id=pkt.conn_id,
                              payload=json.dumps({"accept": False, "reason": reason}).encode()),
                       addr, meta.get("checksum", "crc32"))
            return
        s = self.session = _Session(pkt, addr, meta, self.cfg.out_dir)
        self.log("SYN", f"from {addr[0]}:{addr[1]} conn_id={s.conn_id}: '{s.name}' {s.size:,} bytes,"
                        f" {s.total_packets} packets, {s.protocol.upper()} N={s.window} m={s.seq_bits}")
        self._emit("rx_syn", name=s.name, size=s.size, packets=s.total_packets, protocol=s.protocol,
                   window=s.window, seq_bits=s.seq_bits)
        self._send_synack(s)

    def _send_synack(self, s: _Session) -> None:
        self._send(Packet(SYN | ACK, conn_id=s.conn_id, window=s.rwnd(),
                          payload=json.dumps({"accept": True}).encode()), s.peer, s.checksum)
        self.log("SYNACK", f"sent, rwnd={s.rwnd()}")

    def _ack(self, s: _Session, sel_seq: int) -> None:
        self._emit("rx_ack", seq=sel_seq, ack=s.expected % s.M, rwnd=s.rwnd())
        self._send(Packet(ACK, conn_id=s.conn_id, seq=sel_seq, ack=s.expected % s.M,
                          window=s.rwnd()), s.peer, s.checksum)
        self.stats.acks_sent += 1

    def _on_data(self, s: _Session, pkt: Packet) -> None:
        self.stats.data_packets += 1
        if s.protocol == "sr":
            self._on_data_sr(s, pkt)
        else:
            self._on_data_gbn(s, pkt)

    def _on_data_gbn(self, s: _Session, pkt: Packet) -> None:
        if pkt.seq == s.expected % s.M and s.expected < s.total_packets:
            idx = s.expected
            self._deliver(s, pkt.payload)
            self.log("DELIVER", f"seq={pkt.seq} in order -> packet #{idx} delivered,"
                                f" ACK next={s.expected % s.M}")
            self._emit("rx", seq=pkt.seq, idx=idx, action="deliver", delivered=[idx], base=s.expected)
        else:
            if (s.expected - 1 - pkt.seq) % s.M < s.window or s.expected >= s.total_packets:
                self.stats.duplicates += 1
                why = "duplicate"
            else:
                self.stats.out_of_order_discarded += 1
                why = "out of order"
            self.log("DISCARD", f"seq={pkt.seq} {why} (expecting {s.expected % s.M}) -> discard,"
                                f" re-ACK {s.expected % s.M}")
            self._emit("rx", seq=pkt.seq, idx=None, action="discard" if why == "out of order" else "dup",
                       base=s.expected)
        self._ack(s, pkt.seq)

    def _on_data_sr(self, s: _Session, pkt: Packet) -> None:
        N, M, base = s.window, s.M, s.expected
        off = (pkt.seq - base) % M
        if off < N:  # inside the receive window
            idx = base + off
            action = "outside"
            if idx < s.total_packets:
                if idx in s.buffer:
                    self.stats.duplicates += 1
                    action = "dup"
                    self.log("DISCARD", f"seq={pkt.seq} already buffered")
                elif off == 0:
                    action = "deliver"
                    s.buffer[idx] = pkt.payload
                else:
                    action = "buffer"
                    s.buffer[idx] = pkt.payload
                    self.stats.out_of_order_buffered += 1
                    self.log("BUFFER", f"seq={pkt.seq} out of order -> buffered as #{idx}"
                                       f" (waiting for #{base})")
                self.stats.max_buffered = max(self.stats.max_buffered, len(s.buffer))
                delivered = []
                while s.expected in s.buffer:
                    delivered.append(s.expected)
                    self._deliver(s, s.buffer.pop(s.expected))
                if delivered:
                    rng = f"#{delivered[0]}" + (f"..#{delivered[-1]}" if len(delivered) > 1 else "")
                    self.log("DELIVER", f"seq={pkt.seq} -> delivered {rng}, window base now #{s.expected}")
                self._emit("rx", seq=pkt.seq, idx=idx, action=action, delivered=delivered, base=s.expected)
            self._ack(s, pkt.seq)
        elif off >= M - N:  # old duplicate from the previous window
            self.stats.duplicates += 1
            self.log("DISCARD", f"seq={pkt.seq} old duplicate (ACK was lost) -> ACK it again")
            self._emit("rx", seq=pkt.seq, idx=None, action="old", base=s.expected)
            self._ack(s, pkt.seq)
        else:
            self.stats.outside_window += 1
            self.log("DISCARD", f"seq={pkt.seq} outside both windows -> ignored")
            self._emit("rx", seq=pkt.seq, idx=None, action="outside", base=s.expected)

    def _on_fin(self, s: _Session, pkt: Packet) -> None:
        if s.fin_reply is None:
            try:
                info = json.loads(pkt.payload or b"{}")
            except ValueError:
                info = {}
            s.file.close()
            digest = s.sha.hexdigest()
            expected_sha = info.get("sha256")
            complete = s.expected >= s.total_packets and s.received_bytes == s.size
            ok = complete and digest == expected_sha
            reason = "" if ok else ("incomplete" if not complete else "sha256 mismatch")
            final = _unique_path(s.out_dir, s.name if ok else s.name + ".corrupt")
            os.replace(s.tmp_path, final)
            s.result = ReceiveResult(
                file_name=s.name, path=final, file_bytes=s.received_bytes, expected_bytes=s.size,
                ok=ok, sha256=digest, expected_sha256=expected_sha,
                duration_s=time.monotonic() - s.start, protocol=s.protocol,
                peer=f"{s.peer[0]}:{s.peer[1]}", stats=self.stats.to_dict(), reason=reason)
            s.fin_reply = json.dumps({"ok": ok, "sha256": digest, "bytes": s.received_bytes,
                                      "reason": reason}).encode()
            s.state = TIME_WAIT
            s.time_wait_until = time.monotonic() + self.cfg.linger
            self._emit("rx_fin", ok=ok, reason=reason, sha256=digest, bytes=s.received_bytes)
            self.log("OK" if ok else "FAIL",
                     f"FIN: {s.received_bytes:,} bytes, sha256 {'matches' if ok else 'DOES NOT match'}"
                     f" -> saved {final}")
        self._send(Packet(FIN | ACK, conn_id=s.conn_id, ack=pkt.seq, payload=s.fin_reply),
                   s.peer, s.checksum)
        self.log("FINACK", f"sent (TIME_WAIT {self.cfg.linger:.1f}s)")

    def _abort(self, reason: str) -> ReceiveResult:
        s = self.session
        s.file.close()
        final = _unique_path(s.out_dir, s.name + ".incomplete")
        os.replace(s.tmp_path, final)
        self._send(Packet(RST, conn_id=s.conn_id, payload=reason.encode()), s.peer, s.checksum)
        self.log("FAIL", f"aborting: {reason}")
        return ReceiveResult(
            file_name=s.name, path=final, file_bytes=s.received_bytes, expected_bytes=s.size,
            ok=False, sha256=s.sha.hexdigest(), expected_sha256=None,
            duration_s=time.monotonic() - s.start, protocol=s.protocol,
            peer=f"{s.peer[0]}:{s.peer[1]}", stats=self.stats.to_dict(), reason=reason)
