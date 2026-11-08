"""Counters and time-series recorded during a transfer."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Optional


@dataclass
class SenderStats:
    data_packets_sent: int = 0  # every DATA frame put on the wire
    unique_packets: int = 0  # distinct segments of the file
    retransmissions: int = 0
    timeouts: int = 0
    fast_retransmits: int = 0
    acks_received: int = 0
    dup_acks: int = 0
    corrupt_received: int = 0
    bytes_on_wire: int = 0
    handshake_retries: int = 0
    fin_retries: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ReceiverStats:
    packets_received: int = 0
    data_packets: int = 0
    corrupt_dropped: int = 0
    duplicates: int = 0  # already delivered / already buffered
    out_of_order_discarded: int = 0  # GBN throws these away
    out_of_order_buffered: int = 0  # SR keeps these
    outside_window: int = 0
    acks_sent: int = 0
    max_buffered: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Trace:
    """Time series for plotting. Times are seconds since the data phase began."""
    sends: list = field(default_factory=list)  # (t, index, is_retx)
    acks: list = field(default_factory=list)  # (t, cumulative base)
    cwnd: list = field(default_factory=list)  # (t, cwnd, ssthresh, state)
    rtt: list = field(default_factory=list)  # (t, sample, srtt, rto)
    events: list = field(default_factory=list)  # (t, kind, index)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TransferResult:
    protocol: str
    cc: str
    window: int
    seq_bits: int
    mss: int
    checksum: str
    file_name: str
    file_bytes: int
    packets: int
    handshake_s: float
    data_s: float
    total_s: float
    goodput_kbps: float  # useful file bits / data time
    wire_kbps: float  # all bits sent / data time
    efficiency: float  # unique / total data packets
    srtt_ms: Optional[float]
    final_rto_ms: float
    sha256: str
    verified: Optional[bool]  # receiver's verdict from FIN-ACK (None = unknown)
    stats: dict
    trace: Optional[dict] = None

    def to_dict(self, with_trace: bool = False) -> dict:
        d = asdict(self)
        if not with_trace:
            d.pop("trace", None)
        return d

    def summary(self) -> str:
        v = {True: "VERIFIED (SHA-256 match)", False: "CORRUPTED (SHA-256 mismatch)",
             None: "unverified (no FIN-ACK)"}[self.verified]
        s = self.stats
        srtt = f"{self.srtt_ms:.1f} ms" if self.srtt_ms is not None else "n/a"
        return "\n".join([
            f"  protocol        : {self.protocol.upper()}  window={self.window}  cc={self.cc}"
            f"  seq_bits={self.seq_bits}  checksum={self.checksum}",
            f"  file            : {self.file_name}  {self.file_bytes:,} bytes in {self.packets} packets",
            f"  time            : handshake {self.handshake_s * 1000:.1f} ms, data {self.data_s:.3f} s,"
            f" total {self.total_s:.3f} s",
            f"  goodput         : {self.goodput_kbps:,.1f} kbit/s  ({self.goodput_kbps / 8:,.1f} KB/s)",
            f"  packets sent    : {s['data_packets_sent']}  (retransmitted {s['retransmissions']},"
            f" efficiency {self.efficiency * 100:.1f}%)",
            f"  loss recovery   : {s['timeouts']} timeouts, {s['fast_retransmits']} fast retransmits,"
            f" {s['dup_acks']} dup ACKs, {s['corrupt_received']} corrupt ACKs",
            f"  RTT             : SRTT {srtt}, final RTO {self.final_rto_ms:.0f} ms",
            f"  integrity       : {v}",
        ])


@dataclass
class ReceiveResult:
    file_name: str
    path: Optional[str]
    file_bytes: int
    expected_bytes: int
    ok: bool
    sha256: str
    expected_sha256: Optional[str]
    duration_s: float
    protocol: str
    peer: str
    stats: dict
    reason: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    def summary(self) -> str:
        s = self.stats
        return "\n".join([
            f"  from            : {self.peer}  ({self.protocol.upper()})",
            f"  file            : {self.file_name} -> {self.path}",
            f"  bytes           : {self.file_bytes:,} / {self.expected_bytes:,} in {self.duration_s:.3f} s",
            f"  frames          : {s['packets_received']} received, {s['corrupt_dropped']} failed CRC,"
            f" {s['duplicates']} duplicates",
            f"  out of order    : {s['out_of_order_buffered']} buffered,"
            f" {s['out_of_order_discarded']} discarded, max buffer {s['max_buffered']}",
            f"  integrity       : {'OK - SHA-256 matches' if self.ok else 'FAILED ' + self.reason}",
        ])
