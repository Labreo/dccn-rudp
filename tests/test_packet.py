import pytest

from rudp.packet import ACK, DATA, FIN, HEADER_LEN, SYN, CorruptPacket, Packet, peek


@pytest.mark.parametrize("checksum", ["crc32", "inet16"])
def test_roundtrip(checksum):
    p = Packet(DATA, seq=123456, ack=7, window=32, payload=b"hello world", conn_id=999)
    raw = p.encode(checksum)
    assert len(raw) == HEADER_LEN + 11
    q = Packet.decode(raw)
    assert (q.flags, q.seq, q.ack, q.window, q.payload, q.conn_id) == (DATA, 123456, 7, 32, b"hello world", 999)


def test_header_is_22_bytes():
    assert HEADER_LEN == 22


@pytest.mark.parametrize("checksum", ["crc32", "inet16"])
def test_every_single_bit_flip_is_detected(checksum):
    raw = Packet(SYN | ACK, seq=1, ack=2, payload=b"x" * 40).encode(checksum)
    for bit in range(len(raw) * 8):
        bad = bytearray(raw)
        bad[bit // 8] ^= 1 << (bit % 8)
        with pytest.raises(CorruptPacket):
            Packet.decode(bytes(bad))


def test_truncated_frame_rejected():
    raw = Packet(FIN, payload=b"abc").encode()
    with pytest.raises(CorruptPacket):
        Packet.decode(raw[:-1])
    with pytest.raises(CorruptPacket):
        Packet.decode(raw[:10])


def test_sequence_numbers_wrap_to_32_bits():
    q = Packet.decode(Packet(ACK, seq=2**32 + 5, ack=2**33 + 1).encode())
    assert q.seq == 5 and q.ack == 1


def test_peek_describes_frame():
    assert peek(Packet(DATA, seq=9, payload=b"ab").encode()) == "DATA seq=9 len=2"
