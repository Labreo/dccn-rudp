import os
import random
import zlib

from rudp.checksum import (crc32, crc32_bitwise, crc_check, crc_divide, crc_divide_steps,
                           internet_checksum)


def test_textbook_crc_example():
    # Tanenbaum, Computer Networks: frame 1101011011, G(x) = x^4 + x + 1
    assert crc_divide("1101011011", "10011") == "1110"
    assert crc_check("11010110111110", "10011")
    assert not crc_check("11010110111111", "10011")


def test_forouzan_style_example():
    # dataword 1001, generator 1011 -> remainder 110
    assert crc_divide("1001", "1011") == "110"
    rem, lines = crc_divide_steps("1001", "1011")
    assert rem == "110" and lines[-1].endswith("1001110")


def test_crc32_matches_zlib_and_bitwise():
    rng = random.Random(1)
    for n in (0, 1, 2, 3, 17, 64, 1024, 1500):
        data = bytes(rng.getrandbits(8) for _ in range(n))
        assert crc32(data) == zlib.crc32(data) == crc32_bitwise(data)
    assert crc32(b"123456789") == 0xCBF43926  # standard CRC-32 check value


def test_crc32_matches_polynomial_division():
    # Plain (non-reflected, no init/xorout) CRC-32 by long division equals the
    # table algorithm applied with the same conventions.
    msg = "1011001110001111"
    rem = crc_divide(msg, "1" + format(0x04C11DB7, "032b"))
    assert len(rem) == 32 and set(rem) <= {"0", "1"}


def test_internet_checksum_rfc1071_example():
    data = bytes([0x00, 0x01, 0xF2, 0x03, 0xF4, 0xF5, 0xF6, 0xF7])
    # RFC 1071 section 3: sum = 0xDDF2 -> checksum = ~0xDDF2
    assert internet_checksum(data) == (~0xDDF2) & 0xFFFF


def test_internet_checksum_verifies_to_zero():
    data = os.urandom(100)
    c = internet_checksum(data)
    assert internet_checksum(data + c.to_bytes(2, "big")) == 0


def test_crc_catches_word_swap_inet_does_not():
    data = bytearray(b"ABCDEFGH" * 4)
    swapped = bytearray(data)
    swapped[0:2], swapped[2:4] = data[2:4], data[0:2]
    assert internet_checksum(bytes(data)) == internet_checksum(bytes(swapped))
    assert crc32(bytes(data)) != crc32(bytes(swapped))


def test_crc_detects_all_bursts_up_to_32():
    rng = random.Random(7)
    data = bytes(rng.getrandbits(8) for _ in range(64))
    c = crc32(data)
    for length in range(1, 33):
        for _ in range(30):
            buf = bytearray(data)
            start = rng.randrange(len(buf) * 8 - length + 1)
            bits = {start, start + length - 1} | {start + k for k in range(length) if rng.random() < .5}
            for b in bits:
                buf[b // 8] ^= 1 << (b % 8)
            assert crc32(bytes(buf)) != c
