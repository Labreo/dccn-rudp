import time

from rudp.channel import ImpairedSocket, LinkConfig, make_udp_socket


def _pair(cfg):
    rx = make_udp_socket("127.0.0.1", 0)
    rx.settimeout(2)
    tx = ImpairedSocket(make_udp_socket("127.0.0.1", 0), cfg)
    return tx, rx


def test_loss_rate_is_close_to_configured():
    tx, rx = _pair(LinkConfig(loss=0.3, seed=1))
    for i in range(2000):
        tx.sendto(b"x", rx.getsockname())
    assert 0.25 < tx.stats.dropped_random / 2000 < 0.35
    tx.close(); rx.close()


def test_delay_is_applied():
    tx, rx = _pair(LinkConfig(delay_ms=50))
    t = time.monotonic()
    tx.sendto(b"ping", rx.getsockname())
    rx.recvfrom(100)
    assert 0.045 < time.monotonic() - t < 0.2
    tx.close(); rx.close()


def test_bottleneck_rate_and_queue_drop():
    # 100 kbit/s, 1000-byte frames -> 80 ms each; a queue of 5 must overflow
    tx, rx = _pair(LinkConfig(rate_kbps=100, queue=5))
    for _ in range(20):
        tx.sendto(b"z" * 1000, rx.getsockname())
    assert tx.stats.dropped_queue == 15
    tx.close(flush=False); rx.close()


def test_corruption_changes_bytes():
    tx, rx = _pair(LinkConfig(corrupt=1.0, seed=3))
    tx.sendto(b"\x00" * 64, rx.getsockname())
    data, _ = rx.recvfrom(100)
    assert data != b"\x00" * 64 and tx.stats.corrupted == 1
    tx.close(); rx.close()


def test_jitter_reorders():
    tx, rx = _pair(LinkConfig(delay_ms=1, jitter_ms=30, seed=5))
    for i in range(30):
        tx.sendto(bytes([i]), rx.getsockname())
    got = [rx.recvfrom(10)[0][0] for _ in range(30)]
    assert sorted(got) == list(range(30)) and got != list(range(30))
    tx.close(); rx.close()
