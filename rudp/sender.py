"""ARQ senders: Stop-and-Wait, Go-Back-N and Selective Repeat.

Connection life cycle (same for all three):

    CLOSED --SYN--> SYN_SENT --SYN-ACK--> (send ACK) ESTABLISHED
           --DATA ... all ACKed--> --FIN(sha256)--> FIN_WAIT --FIN-ACK--> CLOSED

Sequence numbers
    Internally every segment has an absolute index 0, 1, 2, ...  On the wire
    only ``index mod 2^m`` is sent (m = ``seq_bits``). The ARQ windows must
    respect the classic limits or the protocols break:

        Stop-and-Wait     window 1,        m >= 1   (alternating bit)
        Go-Back-N         window <= 2^m - 1
        Selective Repeat  window <= 2^(m-1)

    ``python -m rudp demo --seq-bits 2 --window 4 --unsafe`` shows what happens
    when those limits are broken: the receiver accepts an old duplicate as new
    data and the SHA-256 check at the end fails.

ACK semantics
    Every ACK carries ``ack`` = next in-order index expected by the receiver
    (cumulative, like TCP). Selective Repeat ACKs also carry ``seq`` = the
    index of the packet that triggered the ACK (an individual / selective ACK).
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import select
import time
from dataclasses import dataclass, replace
from typing import Callable, Optional

from .channel import ImpairedSocket
from .congestion import make_congestion_control
from .log import EventLog
from .packet import ACK, DATA, FIN, RST, SYN, CorruptPacket, Packet
from .rtt import RTOEstimator
from .stats import SenderStats, Trace, TransferResult

PROTOCOLS = ("sw", "gbn", "sr")


class TransferError(Exception):
    pass


@dataclass
class SenderConfig:
    protocol: str = "sr"  # sw | gbn | sr
    window: int = 16  # max packets in flight (N)
    cc: str = "none"  # none | tahoe | reno
    mss: int = 1024  # payload bytes per packet
    seq_bits: Optional[int] = None  # None -> 1 for sw, 32 otherwise
    checksum: str = "crc32"  # crc32 | inet16
    initial_rto: float = 1.0
    min_rto: float = 0.2
    max_rto: float = 10.0
    max_retries: int = 20  # consecutive timeouts before giving up
    init_ssthresh: float = 64.0
    unsafe: bool = False  # allow windows that violate the seq-space limit

    def normalised(self) -> "SenderConfig":
        if self.protocol not in PROTOCOLS:
            raise ValueError(f"protocol must be one of {PROTOCOLS}")
        c = replace(self)
        if c.protocol == "sw":
            c.window, c.cc = 1, "none"
            if c.seq_bits is None:
                c.seq_bits = 1
        if c.seq_bits is None:
            c.seq_bits = 32
        if not 1 <= c.seq_bits <= 32:
            raise ValueError("seq_bits must be in 1..32")
        if c.window < 1:
            raise ValueError("window must be >= 1")
        M = 1 << c.seq_bits
        limit = {"sw": M - 1, "gbn": M - 1, "sr": M // 2}[c.protocol]
        if c.window > limit and not c.unsafe:
            raise ValueError(
                f"{c.protocol.upper()} window {c.window} is too large for {c.seq_bits}-bit sequence "
                f"numbers (max {limit}). Use --unsafe to try it anyway and watch it break.")
        return c


class BaseSender:
    protocol = "base"

    def __init__(self, sock: ImpairedSocket, dest: tuple, cfg: SenderConfig,
                 log: Optional[EventLog] = None,
                 progress: Optional[Callable[["BaseSender"], None]] = None):
        self.sock = sock
        self.dest = dest
        self.cfg = cfg
        self.M = 1 << cfg.seq_bits
        self.rtt = RTOEstimator(initial=cfg.initial_rto, min_rto=cfg.min_rto, max_rto=cfg.max_rto)
        self.cc = make_congestion_control(cfg.cc, max_cwnd=cfg.window, ssthresh=cfg.init_ssthresh)
        self.stats = SenderStats()
        self.trace = Trace()
        self.log = log or EventLog(False)
        self.progress = progress
        self.conn_id = random.randint(1, 0xFFFF)
        self.rwnd = cfg.window
        self.segments: list[bytes] = []
        self.total = 0
        self.t_data = time.monotonic()
        self._raw = sock.sock
        self._raw.setblocking(False)
        self._last_cwnd = None
        self._last_progress = 0.0

    # ------------------------------------------------------------------ API

    def send_file(self, path: str) -> TransferResult:
        with open(path, "rb") as f:
            data = f.read()
        return self.send_bytes(data, os.path.basename(path))

    def send_bytes(self, data: bytes, name: str = "data.bin") -> TransferResult:
        mss = self.cfg.mss
        self.segments = [data[i:i + mss] for i in range(0, len(data), mss)]
        self.total = len(self.segments)
        sha = hashlib.sha256(data).hexdigest()

        t_start = time.monotonic()
        self._handshake({
            "name": name, "size": len(data), "packets": self.total, "mss": mss,
            "protocol": self.protocol, "window": self.cfg.window,
            "seq_bits": self.cfg.seq_bits, "checksum": self.cfg.checksum,
        })
        self.t_data = time.monotonic()
        self._trace_cwnd()
        self._init_transfer()
        self._run()
        t_data_end = time.monotonic()
        reply = self._teardown(sha, len(data))
        t_end = time.monotonic()

        data_s = max(t_data_end - self.t_data, 1e-9)
        st = self.stats
        st.unique_packets = self.total
        verified = None if reply is None else bool(reply.get("ok"))
        return TransferResult(
            protocol=self.protocol, cc=self.cfg.cc, window=self.cfg.window,
            seq_bits=self.cfg.seq_bits, mss=mss, checksum=self.cfg.checksum,
            file_name=name, file_bytes=len(data), packets=self.total,
            handshake_s=self.t_data - t_start, data_s=data_s, total_s=t_end - t_start,
            goodput_kbps=len(data) * 8 / data_s / 1000,
            wire_kbps=st.bytes_on_wire * 8 / data_s / 1000,
            efficiency=(self.total / st.data_packets_sent) if st.data_packets_sent else 1.0,
            srtt_ms=None if self.rtt.srtt is None else self.rtt.srtt * 1000,
            final_rto_ms=self.rtt.rto * 1000, sha256=sha, verified=verified,
            stats=st.to_dict(), trace=self.trace.to_dict(),
        )

    # ----------------------------------------------------- shared machinery

    def _now(self) -> float:
        return time.monotonic() - self.t_data

    def _send(self, pkt: Packet) -> None:
        pkt.conn_id = self.conn_id
        raw = pkt.encode(self.cfg.checksum)
        self.stats.bytes_on_wire += len(raw)
        self.sock.sendto(raw, self.dest)

    def _recv(self, timeout: float) -> list[Packet]:
        try:
            ready, _, _ = select.select([self._raw], [], [], max(0.0, timeout))
        except InterruptedError:
            return []
        if not ready:
            return []
        out = []
        while True:
            try:
                raw, addr = self._raw.recvfrom(65535)
            except (BlockingIOError, InterruptedError):
                break
            except OSError:  # e.g. ICMP port unreachable reported by the OS
                break
            try:
                pkt = Packet.decode(raw)
            except CorruptPacket as e:
                self.stats.corrupt_received += 1
                self.log("BADCRC", f"discarded corrupt frame from receiver ({e})")
                continue
            if pkt.conn_id != self.conn_id:
                continue
            if pkt.flags & RST:
                raise TransferError("connection reset by receiver: " + pkt.payload.decode(errors="replace"))
            out.append(pkt)
        return out

    def _trace_cwnd(self) -> None:
        cur = (self.cc.cwnd, self.cc.ssthresh, self.cc.state)
        if cur != self._last_cwnd:
            self._last_cwnd = cur
            cw = self.cc.cwnd if self.cc.cwnd != float("inf") else None
            ss = self.cc.ssthresh if self.cc.ssthresh != float("inf") else None
            self.trace.cwnd.append((self._now(), cw, ss, self.cc.state))
            if cw is not None:
                self.log("CWND", f"cwnd={cw:.2f} ssthresh={ss:.1f} [{self.cc.state}]")

    def _rtt_sample(self, sent_at: float) -> None:
        r = time.monotonic() - sent_at
        self.rtt.sample(r)
        self.trace.rtt.append((self._now(), r, self.rtt.srtt, self.rtt.rto))

    def effective_window(self) -> int:
        """min(N, cwnd, rwnd): ARQ window, congestion window, flow control."""
        cwnd = self.cc.window()
        cwnd = self.cfg.window if cwnd == float("inf") else int(cwnd)
        return max(1, min(self.cfg.window, cwnd, self.rwnd))

    def _handshake(self, meta: dict) -> None:
        syn = Packet(SYN, seq=0, window=self.cfg.window, payload=json.dumps(meta).encode())
        for attempt in range(1, self.cfg.max_retries + 1):
            sent_at = time.monotonic()
            self._send(syn)
            self.log("SYN", f"connect to {self.dest[0]}:{self.dest[1]} conn_id={self.conn_id}"
                            f" ({self.protocol.upper()}, N={self.cfg.window}, m={self.cfg.seq_bits})")
            deadline = sent_at + self.rtt.rto
            while (left := deadline - time.monotonic()) > 0:
                for p in self._recv(left):
                    if p.is_(SYN, ACK):
                        if attempt == 1:  # Karn: only sample an un-retransmitted SYN
                            self.rtt.sample(time.monotonic() - sent_at)
                        info = json.loads(p.payload or b"{}")
                        if not info.get("accept", True):
                            raise TransferError("receiver refused: " + info.get("reason", "?"))
                        self.rwnd = max(1, p.window)
                        self.log("SYNACK", f"received, rwnd={p.window}, initial RTT estimate "
                                           f"{(self.rtt.srtt or 0) * 1000:.1f} ms")
                        self._send(Packet(ACK, seq=0, ack=0))
                        self.log("ACK", "3-way handshake complete -> ESTABLISHED")
                        return
            self.stats.handshake_retries += 1
            self.rtt.backoff()
            self.log("TIMEOUT", f"no SYN-ACK, retrying (RTO now {self.rtt.rto * 1000:.0f} ms)")
        raise TransferError(f"no answer from {self.dest[0]}:{self.dest[1]} (is the receiver running?"
                            " is a firewall blocking UDP?)")

    def _teardown(self, sha: str, size: int) -> Optional[dict]:
        fin = Packet(FIN, seq=self.total % self.M,
                     payload=json.dumps({"sha256": sha, "size": size, "packets": self.total}).encode())
        for attempt in range(self.cfg.max_retries):
            sent_at = time.monotonic()
            self._send(fin)
            self.log("FIN", f"all {self.total} packets ACKed, closing (sha256={sha[:12]}...)")
            deadline = sent_at + self.rtt.rto
            while (left := deadline - time.monotonic()) > 0:
                for p in self._recv(left):
                    if p.is_(FIN, ACK):
                        reply = json.loads(p.payload or b"{}")
                        self.log("FINACK", "receiver says " + ("file OK" if reply.get("ok") else
                                                              "file CORRUPT: " + reply.get("reason", "")))
                        return reply
            self.stats.fin_retries += 1
            self.rtt.backoff()
        self.log("FAIL", "no FIN-ACK received; data was ACKed but integrity is unconfirmed")
        return None

    def _run(self) -> None:
        while not self._done():
            self._fill_window()
            deadline = self._next_deadline()
            wait = 0.05 if deadline is None else min(0.5, deadline - time.monotonic())
            for p in self._recv(wait):
                if p.flags & ACK and not p.flags & (SYN | FIN):
                    self.stats.acks_received += 1
                    self.rwnd = max(1, p.window)
                    self._on_ack(p)
                elif p.is_(SYN, ACK):  # our handshake ACK was lost; re-send it
                    self._send(Packet(ACK, seq=0, ack=0))
            self._check_timeouts()
            self._trace_cwnd()
            if self.progress and time.monotonic() - self._last_progress > 0.2:
                self._last_progress = time.monotonic()
                self.progress(self)

    def _send_data(self, i: int, retx: bool) -> None:
        self.stats.data_packets_sent += 1
        if retx:
            self.stats.retransmissions += 1
        self.trace.sends.append((self._now(), i, retx))
        self._send(Packet(DATA, seq=i % self.M, window=self.cfg.window, payload=self.segments[i]))
        self.log("RETX" if retx else "SEND", f"DATA #{i} seq={i % self.M} "
                                             f"(window={self.effective_window()})")

    # ---------------------------------------------- protocol-specific hooks

    def acked_count(self) -> int:
        raise NotImplementedError

    def _init_transfer(self) -> None: ...
    def _done(self) -> bool: ...
    def _fill_window(self) -> None: ...
    def _next_deadline(self) -> Optional[float]: ...
    def _on_ack(self, p: Packet) -> None: ...
    def _check_timeouts(self) -> None: ...


class GoBackNSender(BaseSender):
    """Go-Back-N: one timer (for the oldest unACKed packet), cumulative ACKs.

    On timeout every packet from ``base`` onwards is sent again ("go back N").
    With congestion control enabled, 3 duplicate ACKs trigger fast
    retransmission of ``base`` only.
    """

    protocol = "gbn"

    def _init_transfer(self) -> None:
        self.base = 0  # oldest unACKed index
        self.next = 0  # next index to (re)send
        self.max_sent = 0  # highest index ever sent + 1
        self.sent_at: dict[int, float] = {}
        self.retx: set[int] = set()  # indices sent more than once (Karn)
        self.timer: Optional[float] = None
        self.dupacks = 0
        self.timeouts_in_row = 0

    def acked_count(self) -> int:
        return self.base

    def _done(self) -> bool:
        return self.base >= self.total

    def _fill_window(self) -> None:
        while self.next < self.total and self.next - self.base < self.effective_window():
            i = self.next
            retx = i < self.max_sent
            if retx:
                self.retx.add(i)
            self.max_sent = max(self.max_sent, i + 1)
            self.sent_at[i] = time.monotonic()
            self._send_data(i, retx)
            if self.timer is None:
                self.timer = time.monotonic()
            self.next += 1

    def _next_deadline(self) -> Optional[float]:
        return None if self.timer is None else self.timer + self.rtt.rto

    def _on_ack(self, p: Packet) -> None:
        now = time.monotonic()
        off = (p.ack - self.base) % self.M  # how far the cumulative ACK moved
        in_flight = self.max_sent - self.base
        if off == 0:
            if self.next > self.base:
                self.dupacks += 1
                self.stats.dup_acks += 1
                self.log("DUPACK", f"ack={p.ack} (duplicate #{self.dupacks}, base=#{self.base})")
                if self.cc.on_dup_ack(self.dupacks, self.next - self.base):
                    # The GBN receiver discarded everything after the hole, so
                    # "fast retransmit" means going back N right now instead of
                    # waiting for the timer.
                    self.stats.fast_retransmits += 1
                    self.trace.events.append((self._now(), "fastretx", self.base))
                    self.log("FASTRETX", f"3 duplicate ACKs -> go back to #{self.base} now")
                    self.next = self.base
                    self.timer = None
            return
        if off > in_flight:
            return  # stale ACK from before a go-back; ignore
        last = self.base + off - 1
        if last not in self.retx and last in self.sent_at:
            self._rtt_sample(self.sent_at[last])
        for i in range(self.base, self.base + off):
            self.sent_at.pop(i, None)
        self.base += off
        self.next = max(self.next, self.base)
        self.rtt.reset_backoff()
        self.dupacks = 0
        self.timeouts_in_row = 0
        self.cc.on_new_ack(off)
        self.trace.acks.append((self._now(), self.base))
        self.log("ACK", f"ack={p.ack} -> {off} packet(s) ACKed, base=#{self.base}")
        self.timer = now if self.base < self.next else None

    def _check_timeouts(self) -> None:
        if self.timer is None or time.monotonic() < self.timer + self.rtt.rto:
            return
        self.stats.timeouts += 1
        self.timeouts_in_row += 1
        if self.timeouts_in_row > self.cfg.max_retries:
            raise TransferError(f"packet #{self.base} timed out {self.cfg.max_retries} times; giving up")
        self.trace.events.append((self._now(), "timeout", self.base))
        self.cc.on_timeout(self.next - self.base)
        self.rtt.backoff()
        self.log("TIMEOUT", f"timer for #{self.base} expired -> go back to #{self.base}"
                            f" (resend {self.next - self.base}), RTO={self.rtt.rto * 1000:.0f} ms")
        self.next = self.base  # Go back N
        self.dupacks = 0
        self.timer = None


class StopAndWaitSender(GoBackNSender):
    """Stop-and-Wait ARQ = Go-Back-N with window N = 1.

    Send one frame, start the timer, wait for its ACK; on timeout resend.
    With the default 1-bit sequence number this is the Alternating Bit
    Protocol. ``SenderConfig.normalised`` forces window = 1 and cc = none.
    """

    protocol = "sw"


class SelectiveRepeatSender(BaseSender):
    """Selective Repeat: one timer *per packet*, individual ACKs.

    Only the packets that actually timed out (or that 3 duplicate ACKs point
    at) are retransmitted; the receiver buffers out-of-order packets.
    """

    protocol = "sr"

    def _init_transfer(self) -> None:
        self.base = 0
        self.next = 0
        self.unacked: dict[int, float] = {}  # index -> time last sent (its timer)
        self.acked: set[int] = set()  # ACKed but above base
        self.retx: set[int] = set()
        self.retries: dict[int, int] = {}
        self.dupacks = 0
        self.recovery_point = 0  # one window reduction per window of data

    def acked_count(self) -> int:
        return self.base + len(self.acked)

    def _done(self) -> bool:
        return self.base >= self.total

    def _fill_window(self) -> None:
        while self.next < self.total and self.next - self.base < self.effective_window():
            i = self.next
            self.unacked[i] = time.monotonic()
            self._send_data(i, False)
            self.next += 1

    def _next_deadline(self) -> Optional[float]:
        if not self.unacked:
            return None
        return min(self.unacked.values()) + self.rtt.rto

    def _mark_acked(self, i: int, sample: bool) -> bool:
        sent_at = self.unacked.pop(i, None)
        if sent_at is None:
            return False
        if sample and i not in self.retx:
            self._rtt_sample(sent_at)
        if i >= self.base:
            self.acked.add(i)
        return True

    def _retransmit(self, i: int) -> None:
        self.retx.add(i)
        self.retries[i] = self.retries.get(i, 0) + 1
        if self.retries[i] > self.cfg.max_retries:
            raise TransferError(f"packet #{i} retransmitted {self.cfg.max_retries} times; giving up")
        self.unacked[i] = time.monotonic()
        self._send_data(i, True)

    def _on_ack(self, p: Packet) -> None:
        outstanding = self.next - self.base
        old_base = self.base
        sel = (p.seq - self.base) % self.M  # which packet this ACK is for
        got_sel = sel < outstanding and self._mark_acked(self.base + sel, sample=True)
        cum = (p.ack - self.base) % self.M  # cumulative point
        if 0 < cum <= outstanding:
            for j in range(self.base, self.base + cum):
                self._mark_acked(j, sample=False)
                self.acked.add(j)
        while self.base in self.acked:  # slide the window
            self.acked.discard(self.base)
            self.base += 1
        moved = self.base - old_base
        if moved:
            self.rtt.reset_backoff()
            self.dupacks = 0
            self.cc.on_new_ack(moved)
            self.trace.acks.append((self._now(), self.base))
            self.log("ACK", f"sack=#{old_base + sel if got_sel else '-'} cum={p.ack} ->"
                            f" window slides by {moved}, base=#{self.base}")
        elif self.base < self.next:
            # ACK for a packet above the hole: the hole is probably lost
            self.dupacks += 1
            self.stats.dup_acks += 1
            self.log("ACK" if got_sel else "DUPACK",
                     f"sack=#{old_base + sel if got_sel else '-'} buffered by receiver,"
                     f" still missing #{self.base} (dup #{self.dupacks})")
            if self.cc.on_dup_ack(self.dupacks, len(self.unacked)) and self.base in self.unacked:
                self.stats.fast_retransmits += 1
                self.recovery_point = self.next
                self.trace.events.append((self._now(), "fastretx", self.base))
                self.log("FASTRETX", f"3 duplicate ACKs -> resend #{self.base} now")
                self._retransmit(self.base)
                return
        self._sack_repair()

    def _sack_repair(self) -> None:
        """Loss recovery using the selective-ACK information (like TCP SACK).

        While recovering from a loss event, every arriving ACK may clock out
        one retransmission: the lowest hole below the highest SACKed packet
        whose last copy has been out for longer than one SRTT (if it had
        arrived, its ACK would be here by now). This repairs several losses
        from the same window within about one RTT, where plain Reno would
        need one RTT per hole or fall back to a timeout.
        """
        if self.cfg.cc == "none" or self.base >= self.recovery_point or not self.acked:
            return
        highest = max(self.acked)
        age = self.rtt.srtt if self.rtt.srtt is not None else self.rtt.rto / 2
        now = time.monotonic()
        for i in range(self.base, highest):
            t = self.unacked.get(i)
            if t is not None and now - t > age:
                self.stats.fast_retransmits += 1
                self.trace.events.append((self._now(), "fastretx", i))
                self.log("FASTRETX", f"SACK shows hole at #{i} (later packets arrived) -> resend")
                self._retransmit(i)
                return

    def _check_timeouts(self) -> None:
        now = time.monotonic()
        rto = self.rtt.rto
        expired = sorted(i for i, t in self.unacked.items() if now >= t + rto)
        if not expired:
            return
        self.stats.timeouts += 1
        self.trace.events.append((self._now(), "timeout", expired[0]))
        new_loss_event = expired[0] >= self.recovery_point
        if new_loss_event:  # cut the window once per window of data
            self.cc.on_timeout(len(self.unacked))
            self.recovery_point = self.next
        if new_loss_event or expired[0] in self.retx:  # a retransmission was lost too
            self.rtt.backoff()
        budget = len(expired) if self.cc.window() == float("inf") else max(1, int(self.cc.window()))
        self.log("TIMEOUT", f"timer(s) expired for {['#%d' % i for i in expired[:8]]}"
                            f"{'...' if len(expired) > 8 else ''} -> resend only those"
                            f" (RTO={self.rtt.rto * 1000:.0f} ms)")
        for k, i in enumerate(expired):
            if k < budget:
                self._retransmit(i)
            else:
                self.unacked[i] = now  # restart its timer; cwnd does not allow more now


def make_sender(sock: ImpairedSocket, dest: tuple, cfg: SenderConfig, **kw) -> BaseSender:
    cfg = cfg.normalised()
    cls = {"sw": StopAndWaitSender, "gbn": GoBackNSender, "sr": SelectiveRepeatSender}[cfg.protocol]
    return cls(sock, dest, cfg, **kw)
