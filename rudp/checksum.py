"""Error detection codes (Data Link Layer, Unit 3).

Three implementations, all written from scratch:

* ``crc_divide``      - textbook modulo-2 polynomial long division on bit
                        strings. Slow, but it is exactly what is done on paper
                        in the exam, so it is used to check the other two.
* ``crc32``           - table-driven CRC-32 (IEEE 802.3 / Ethernet polynomial
                        0x04C11DB7). This is what every RUDP packet carries.
* ``internet_checksum`` - 16-bit one's-complement sum used by IP, UDP and TCP
                        (RFC 1071). Offered as a weaker alternative so the two
                        can be compared experimentally.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# 1. Paper-and-pencil CRC: modulo-2 long division
# ---------------------------------------------------------------------------


def crc_divide(message_bits: str, generator_bits: str) -> str:
    """Return the CRC remainder for ``message_bits`` using ``generator_bits``.

    Follows the textbook procedure: append r = deg(G) zero bits to the
    message, divide by G using XOR (no carries / borrows), the remainder is
    the CRC.

    >>> crc_divide("1101011011", "10011")   # Tanenbaum's worked example
    '1110'
    """
    if not message_bits or not generator_bits or generator_bits[0] != "1":
        raise ValueError("generator must start with a 1 bit")
    r = len(generator_bits) - 1
    dividend = [int(b) for b in message_bits + "0" * r]
    gen = [int(b) for b in generator_bits]
    for i in range(len(message_bits)):
        if dividend[i] == 1:  # leading bit is 1 -> "subtract" (XOR) generator
            for j in range(len(gen)):
                dividend[i + j] ^= gen[j]
    return "".join(str(b) for b in dividend[-r:])


def crc_divide_steps(message_bits: str, generator_bits: str) -> tuple[str, list[str]]:
    """Like ``crc_divide`` but also returns the long-division working, line
    by line, in the layout used on paper. Handy for checking exam answers."""
    r = len(generator_bits) - 1
    work = list(message_bits + "0" * r)
    width = len(work)
    lines = [f"  {''.join(work)}    (message + {r} zeros)"]
    for i in range(len(message_bits)):
        if work[i] == "1":
            lines.append("  " + " " * i + generator_bits + " " * (width - i - len(generator_bits))
                         + f"    XOR G at bit {i}")
            for j, g in enumerate(generator_bits):
                work[i + j] = "1" if work[i + j] != g else "0"
            lines.append("  " + " " * i + "-" * len(generator_bits))
            lines.append("  " + "".join(work))
    rem = "".join(work[-r:])
    lines.append(f"  remainder (CRC) = {rem}")
    lines.append(f"  transmitted frame = {message_bits}{rem}")
    return rem, lines


def crc_check(codeword_bits: str, generator_bits: str) -> bool:
    """Receiver side: a codeword is valid iff it divides evenly by G."""
    r = len(generator_bits) - 1
    data, crc = codeword_bits[:-r], codeword_bits[-r:]
    return crc_divide(data, generator_bits) == crc


# ---------------------------------------------------------------------------
# 2. CRC-32 (the one used on the wire)
# ---------------------------------------------------------------------------

# 0x04C11DB7 is x^32+x^26+x^23+x^22+x^16+x^12+x^11+x^10+x^8+x^7+x^5+x^4+x^2+x+1.
# Ethernet transmits LSB first, so the algorithm works on the bit-reversed
# polynomial 0xEDB88320.
CRC32_POLY = 0x04C11DB7
CRC32_POLY_REFLECTED = 0xEDB88320


def _build_crc32_table() -> list[int]:
    table = []
    for byte in range(256):
        crc = byte
        for _ in range(8):  # process one bit at a time (long division)
            if crc & 1:
                crc = (crc >> 1) ^ CRC32_POLY_REFLECTED
            else:
                crc >>= 1
        table.append(crc)
    return table


_CRC32_TABLE = _build_crc32_table()


def crc32(data: bytes, crc: int = 0) -> int:
    """CRC-32 of ``data``. Identical output to ``zlib.crc32`` / Ethernet FCS.

    The 256-entry table holds the remainder of every possible byte, so the
    division advances 8 bits per step instead of 1.
    """
    crc ^= 0xFFFFFFFF
    table = _CRC32_TABLE
    for b in data:
        crc = table[(crc ^ b) & 0xFF] ^ (crc >> 8)
    return crc ^ 0xFFFFFFFF


def crc32_bitwise(data: bytes) -> int:
    """Same CRC-32, computed one bit at a time (no table). Used in tests."""
    crc = 0xFFFFFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ CRC32_POLY_REFLECTED if crc & 1 else crc >> 1
    return crc ^ 0xFFFFFFFF


# ---------------------------------------------------------------------------
# 3. Internet checksum (RFC 1071)
# ---------------------------------------------------------------------------


def internet_checksum(data: bytes) -> int:
    """16-bit one's-complement of the one's-complement sum of 16-bit words."""
    if len(data) % 2:
        data += b"\x00"  # pad odd length with a zero byte
    total = 0
    for i in range(0, len(data), 2):
        total += (data[i] << 8) | data[i + 1]
    while total >> 16:  # fold carries back in (end-around carry)
        total = (total & 0xFFFF) + (total >> 16)
    return (~total) & 0xFFFF


CHECKSUMS = {
    "crc32": crc32,
    "inet16": internet_checksum,
}
