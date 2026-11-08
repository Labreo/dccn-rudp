"""RUDP packet format (framing).

Every UDP datagram carries exactly one RUDP packet:

     0                   1                   2                   3
     0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
    +-------------------------------+---------------+---------------+
    |        magic = 0x5244 "RD"    |   version=1   |     flags     |
    +-------------------------------+---------------+---------------+
    |        connection id          |                               |
    +-------------------------------+                               +
    |                       sequence number (32)                    |
    +                               +-------------------------------+
    |                               |                               |
    +-------------------------------+                               +
    |                    acknowledgement number (32)                |
    +                               +-------------------------------+
    |                               |    receive window (packets)   |
    +-------------------------------+-------------------------------+
    |        payload length         |                               |
    +-------------------------------+                               +
    |                     checksum (CRC-32 or inet16)               |
    +                               +-------------------------------+
    |                               |      payload ...              |
    +-------------------------------+-------------------------------+

    flags: SYN=0x01 ACK=0x02 FIN=0x04 DATA=0x08 RST=0x10 CK16=0x20

Header is 22 bytes. The checksum covers header (with checksum field = 0)
plus payload, so a flipped bit anywhere in the frame is detected.

Sequence numbers are carried modulo 2^m (m = "seq_bits", negotiated in the
SYN). m = 32 by default; Stop-and-Wait uses m = 1 (alternating bit).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Optional

from .checksum import crc32, internet_checksum

MAGIC = 0x5244
VERSION = 1
HEADER_FMT = "!HBBHIIHHI"
HEADER_LEN = struct.calcsize(HEADER_FMT)  # 22 bytes
MAX_PAYLOAD = 0xFFFF - HEADER_LEN

SYN = 0x01
ACK = 0x02
FIN = 0x04
DATA = 0x08
RST = 0x10
CK16 = 0x20  # set when the Internet checksum is used instead of CRC-32

_FLAG_NAMES = [(SYN, "SYN"), (ACK, "ACK"), (FIN, "FIN"), (DATA, "DATA"), (RST, "RST")]


class CorruptPacket(Exception):
    """Raised when a received frame fails the checksum or sanity checks."""


def _checksum(flags: int, frame: bytes) -> int:
    return internet_checksum(frame) if flags & CK16 else crc32(frame)


def flag_str(flags: int) -> str:
    names = [n for bit, n in _FLAG_NAMES if flags & bit]
    return "|".join(names) or "-"


@dataclass
class Packet:
    flags: int
    seq: int = 0
    ack: int = 0
    window: int = 0
    payload: bytes = b""
    conn_id: int = 0

    # -- serialisation -----------------------------------------------------

    def encode(self, checksum: str = "crc32") -> bytes:
        if len(self.payload) > MAX_PAYLOAD:
            raise ValueError("payload too large")
        flags = self.flags | (CK16 if checksum == "inet16" else 0)
        header = struct.pack(
            HEADER_FMT,
            MAGIC,
            VERSION,
            flags,
            self.conn_id & 0xFFFF,
            self.seq & 0xFFFFFFFF,
            self.ack & 0xFFFFFFFF,
            min(self.window, 0xFFFF),
            len(self.payload),
            0,  # checksum placeholder
        )
        cks = _checksum(flags, header + self.payload)
        return header[:-4] + struct.pack("!I", cks) + self.payload

    @classmethod
    def decode(cls, raw: bytes) -> "Packet":
        if len(raw) < HEADER_LEN:
            raise CorruptPacket("frame shorter than header")
        magic, ver, flags, conn, seq, ack, win, length, cks = struct.unpack_from(HEADER_FMT, raw)
        zeroed = raw[: HEADER_LEN - 4] + b"\x00\x00\x00\x00" + raw[HEADER_LEN:]
        if _checksum(flags, zeroed) != cks:
            raise CorruptPacket("checksum mismatch")
        if magic != MAGIC or ver != VERSION:
            raise CorruptPacket("bad magic/version")
        if length != len(raw) - HEADER_LEN:
            raise CorruptPacket("length mismatch")
        return cls(flags & ~CK16, seq, ack, win, bytes(raw[HEADER_LEN:]), conn)

    # -- helpers -----------------------------------------------------------

    def is_(self, *flags: int) -> bool:
        return all(self.flags & f for f in flags)

    def describe(self) -> str:
        return describe_fields(self.flags, self.seq, self.ack, len(self.payload))


def describe_fields(flags: int, seq: int, ack: int, length: int) -> str:
    f = flag_str(flags)
    if flags & DATA:
        return f"DATA seq={seq} len={length}"
    if flags & ACK and not flags & (SYN | FIN):
        return f"ACK ack={ack} sack={seq}"
    return f"{f} seq={seq} ack={ack}"


def peek_fields(raw: bytes) -> Optional[dict]:
    """Header fields of a raw frame without verifying it (None if too short)."""
    try:
        _, _, flags, _, seq, ack, _, length, _ = struct.unpack_from(HEADER_FMT, raw)
    except struct.error:
        return None
    flags &= ~CK16
    kind = ("DATA" if flags & DATA else "SYN" if flags & SYN else "FIN" if flags & FIN
            else "ACK" if flags & ACK else "OTHER")
    return {"kind": kind, "seq": seq, "ack": ack, "len": length}


def peek(raw: bytes) -> str:
    """Describe a raw frame without verifying it (used by the link logger)."""
    try:
        _, _, flags, _, seq, ack, _, length, _ = struct.unpack_from(HEADER_FMT, raw)
    except struct.error:
        return "<runt frame>"
    return describe_fields(flags & ~CK16, seq, ack, length)
