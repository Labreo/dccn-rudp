import os

import pytest

from rudp.channel import LinkConfig
from rudp.local import run_local_transfer
from rudp.sender import SenderConfig

DATA = os.urandom(40 * 1024 + 123)  # 41 packets, last one short

HARSH = LinkConfig(loss=0.1, corrupt=0.03, duplicate=0.03, delay_ms=3, jitter_ms=3, seed=1)
ACK_HARSH = LinkConfig(loss=0.1, corrupt=0.03, delay_ms=3, seed=2)


@pytest.mark.parametrize("proto,cc", [("sw", "none"), ("gbn", "none"), ("sr", "none"),
                                      ("gbn", "tahoe"), ("gbn", "reno"), ("sr", "tahoe"), ("sr", "reno")])
def test_file_arrives_intact_over_bad_link(proto, cc):
    s, r = run_local_transfer(DATA, SenderConfig(protocol=proto, cc=cc, window=8, min_rto=0.05),
                              HARSH, ACK_HARSH)
    assert s.verified is True
    assert r.ok and r.file_bytes == len(DATA)
    assert s.stats["retransmissions"] > 0  # the link really did lose packets


def test_inet16_checksum_mode():
    s, r = run_local_transfer(DATA, SenderConfig(protocol="sr", checksum="inet16", min_rto=0.05),
                              LinkConfig(corrupt=0.1, seed=4))
    assert s.verified and r.stats["corrupt_dropped"] > 0


def test_empty_file():
    s, r = run_local_transfer(b"", SenderConfig(protocol="sr"))
    assert s.verified and r.file_bytes == 0


def test_sw_uses_alternating_bit():
    s, _ = run_local_transfer(DATA[:5000], SenderConfig(protocol="sw"))
    assert s.seq_bits == 1 and s.window == 1 and s.verified


def test_small_sequence_space_within_limits_is_safe():
    cfg = SenderConfig(protocol="sr", window=4, seq_bits=3, min_rto=0.05)
    s, r = run_local_transfer(DATA, cfg, HARSH, LinkConfig(loss=0.3, delay_ms=3, seed=9))
    assert s.verified and r.ok


def test_window_too_large_for_seq_space_is_refused():
    with pytest.raises(ValueError):
        SenderConfig(protocol="sr", window=5, seq_bits=3).normalised()
    with pytest.raises(ValueError):
        SenderConfig(protocol="gbn", window=4, seq_bits=2).normalised()


def test_unsafe_window_corrupts_and_is_detected():
    """SR with N=6 > 2^(3-1): lost ACKs make old duplicates look new."""
    failures = 0
    for seed in range(4):
        cfg = SenderConfig(protocol="sr", window=6, seq_bits=3, unsafe=True, min_rto=0.05, max_retries=10)
        try:
            s, r = run_local_transfer(DATA, cfg, LinkConfig(loss=0.1, delay_ms=3, seed=seed),
                                      LinkConfig(loss=0.4, delay_ms=3, seed=seed + 50))
            failures += s.verified is False
        except Exception:
            failures += 1
    assert failures >= 1


def test_receiver_sanitises_file_name(tmp_path):
    s, r = run_local_transfer(b"abc", SenderConfig(protocol="sr"), name="../../etc/evil.txt",
                              out_dir=str(tmp_path))
    assert r.ok and os.path.dirname(r.path) == str(tmp_path)
    assert os.path.basename(r.path) == "evil.txt"
