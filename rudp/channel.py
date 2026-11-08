"""Unreliable link emulator (Physical / Data-link impairments, Units 1-3).

A real LAN almost never loses packets, so to *see* the ARQ protocols work we
put an emulated link in front of every socket. ``ImpairedSocket.sendto``
pushes each outgoing frame through this pipeline:

    frame --> [ bottleneck queue ] --> [ transmitter: rate R ] --> [ wire ] --> peer
              drop-tail, Q pkts         tx time = L / R             loss p, burst loss,
                                                                    bit errors, duplicates,
                                                                    propagation delay d,
                                                                    jitter (=> reordering)

* Transmission delay   Tt = L / R           (frame length / bandwidth)
* Propagation delay    Tp = d               (``delay_ms``)
* Queueing delay       waits behind earlier frames in the queue
* Queue overflow       drop-tail when more than ``queue`` frames are waiting.
                       This is what makes congestion control necessary.
* Random loss          Bernoulli with probability ``loss``
* Burst loss           Gilbert-Elliott two-state model (``burst_p``/``burst_r``)
* Corruption           1-3 random bits flipped with probability ``corrupt``
* Duplication          frame delivered twice with probability ``duplicate``
* Jitter               extra uniform [0, jitter] delay, so frames can overtake
                       each other (reordering)

Impairments are applied in the *sending* direction only; give the receiver
its own ``ImpairedSocket`` to impair the ACK direction.
"""

from __future__ import annotations

import collections
import heapq
import random
import socket
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Callable, Optional

EventHook = Callable[[str, bytes], None]


@dataclass
class LinkConfig:
    loss: float = 0.0  # probability a frame is dropped on the wire
    corrupt: float = 0.0  # probability a frame gets bit errors
    duplicate: float = 0.0  # probability a frame is delivered twice
    delay_ms: float = 0.0  # one-way propagation delay
    jitter_ms: float = 0.0  # extra random delay in [0, jitter]
    rate_kbps: float = 0.0  # bottleneck bandwidth, 0 = unlimited
    queue: int = 100  # bottleneck buffer size in frames
    burst_p: float = 0.0  # Gilbert-Elliott P(good -> bad)
    burst_r: float = 0.5  # Gilbert-Elliott P(bad -> good)
    seed: Optional[int] = None

    def is_passthrough(self) -> bool:
        return not (self.rate_kbps or self.delay_ms or self.jitter_ms)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ChannelStats:
    offered: int = 0
    delivered: int = 0
    dropped_random: int = 0
    dropped_burst: int = 0
    dropped_queue: int = 0
    corrupted: int = 0
    duplicated: int = 0
    max_queue: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(order=True)
class _Scheduled:
    release: float
    order: int
    data: bytes = field(compare=False)
    addr: tuple = field(compare=False)


class ImpairedSocket:
    """Wraps a UDP socket; outgoing datagrams pass through an emulated link."""

    def __init__(self, sock: socket.socket, cfg: Optional[LinkConfig] = None,
                 on_event: Optional[EventHook] = None):
        self.sock = sock
        self.cfg = cfg or LinkConfig()
        self.stats = ChannelStats()
        self.on_event = on_event
        self._rng = random.Random(self.cfg.seed)
        self._heap: list[_Scheduled] = []
        self._order = 0
        self._cv = threading.Condition()
        self._closed = False
        self._tx_free_at = 0.0
        self._in_queue: collections.deque[float] = collections.deque()
        self._bad_state = False
        self._thread: Optional[threading.Thread] = None
        if not self.cfg.is_passthrough():
            self._thread = threading.Thread(target=self._pump, name="link", daemon=True)
            self._thread.start()

    # -- socket-like API ---------------------------------------------------

    def fileno(self) -> int:
        return self.sock.fileno()

    def getsockname(self):
        return self.sock.getsockname()

    def recvfrom(self, bufsize: int):
        return self.sock.recvfrom(bufsize)

    def sendto(self, data: bytes, addr) -> None:
        cfg, rng, st = self.cfg, self._rng, self.stats
        now = time.monotonic()
        st.offered += 1

        # 1. Bottleneck queue + transmitter (store-and-forward, drop-tail)
        depart = now
        if cfg.rate_kbps > 0:
            with self._cv:
                q = self._in_queue
                while q and q[0] <= now:
                    q.popleft()
                if len(q) >= cfg.queue:
                    st.dropped_queue += 1
                    self._emit("QDROP", data)
                    return
                tx_time = len(data) * 8 / (cfg.rate_kbps * 1000.0)
                depart = max(now, self._tx_free_at) + tx_time
                self._tx_free_at = depart
                q.append(depart)
                st.max_queue = max(st.max_queue, len(q))

        # 2. Losses on the wire (the frame still used up transmitter time)
        if cfg.burst_p > 0:
            if self._bad_state:
                if rng.random() < cfg.burst_r:
                    self._bad_state = False
            elif rng.random() < cfg.burst_p:
                self._bad_state = True
            if self._bad_state:
                st.dropped_burst += 1
                self._emit("BURST", data)
                return
        if cfg.loss > 0 and rng.random() < cfg.loss:
            st.dropped_random += 1
            self._emit("DROP", data)
            return

        # 3. Bit errors
        if cfg.corrupt > 0 and rng.random() < cfg.corrupt:
            original = data
            buf = bytearray(data)
            for _ in range(rng.randint(1, 3)):
                bit = rng.randrange(len(buf) * 8)
                buf[bit // 8] ^= 1 << (bit % 8)
            data = bytes(buf)
            st.corrupted += 1
            self._emit("CORRUPT", original)  # report which frame was hit, not the garbled bytes

        copies = 1
        if cfg.duplicate > 0 and rng.random() < cfg.duplicate:
            copies = 2
            st.duplicated += 1
            self._emit("DUP", data)

        # 4. Propagation delay + jitter, then hand to the real socket
        for _ in range(copies):
            st.delivered += 1
            if self._thread is None:
                self._raw_send(data, addr)
                continue
            release = depart + cfg.delay_ms / 1000.0
            if cfg.jitter_ms:
                release += rng.random() * cfg.jitter_ms / 1000.0
            with self._cv:
                self._order += 1
                heapq.heappush(self._heap, _Scheduled(release, self._order, data, addr))
                self._cv.notify()

    def close(self, flush: bool = True) -> None:
        if self._thread is not None:
            if flush:
                deadline = time.monotonic() + 2.0
                while self._heap and time.monotonic() < deadline:
                    time.sleep(0.005)
            with self._cv:
                self._closed = True
                self._cv.notify()
            self._thread.join(timeout=1.0)
        self.sock.close()

    # -- internals ---------------------------------------------------------

    def _emit(self, kind: str, data: bytes) -> None:
        if self.on_event:
            self.on_event(kind, data)

    def _raw_send(self, data: bytes, addr) -> None:
        try:
            self.sock.sendto(data, addr)
        except OSError:
            pass  # e.g. ENOBUFS / host unreachable: behaves like a lost frame

    def _pump(self) -> None:
        with self._cv:
            while not self._closed:
                if not self._heap:
                    self._cv.wait()
                    continue
                wait = self._heap[0].release - time.monotonic()
                if wait > 0:
                    self._cv.wait(wait)
                    continue
                item = heapq.heappop(self._heap)
                self._raw_send(item.data, item.addr)


def make_udp_socket(bind_host: str = "0.0.0.0", port: int = 0) -> socket.socket:
    """UDP socket with large buffers so the OS itself does not drop bursts."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    for opt in (socket.SO_RCVBUF, socket.SO_SNDBUF):
        try:
            s.setsockopt(socket.SOL_SOCKET, opt, 4 * 1024 * 1024)
        except OSError:
            pass
    s.bind((bind_host, port))
    return s
