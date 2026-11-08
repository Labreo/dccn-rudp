from rudp.congestion import CONG_AVOID, FAST_RECOVERY, SLOW_START, Reno, Tahoe, make_congestion_control
from rudp.rtt import RTOEstimator


def test_rto_first_sample_and_update():
    r = RTOEstimator(min_rto=0.0)
    r.sample(0.100)
    assert r.srtt == 0.100 and abs(r.rttvar - 0.050) < 1e-12
    assert abs(r.rto - 0.300) < 1e-9  # 0.1 + 4 * 0.05
    r.sample(0.200)
    assert abs(r.rttvar - (0.75 * 0.05 + 0.25 * 0.1)) < 1e-12
    assert abs(r.srtt - (0.875 * 0.1 + 0.125 * 0.2)) < 1e-12


def test_rto_backoff_and_clamp():
    r = RTOEstimator(initial=1.0, min_rto=0.2, max_rto=4.0)
    assert r.backoff() == 2.0 and r.backoff() == 4.0 and r.backoff() == 4.0
    r.sample(0.01)
    assert r.rto == 0.2  # clamped to minimum


def test_reset_backoff_restores_computed_rto():
    r = RTOEstimator(min_rto=0.0)
    r.sample(0.1)
    base = r.rto
    r.backoff(); r.backoff()
    assert r.rto == 4 * base
    assert r.reset_backoff() == base


def test_slow_start_doubles_per_rtt():
    cc = Tahoe(max_cwnd=1000, ssthresh=1000)
    for expected in (2, 4, 8, 16):
        cc.on_new_ack(int(cc.cwnd))  # one window ACKed = one RTT
        assert cc.cwnd == expected
    assert cc.state == SLOW_START


def test_congestion_avoidance_adds_one_per_rtt():
    cc = Tahoe(max_cwnd=1000, init_cwnd=10, ssthresh=10)
    cc.on_new_ack(10)
    assert abs(cc.cwnd - 11) < 0.1 and cc.state == CONG_AVOID


def test_tahoe_resets_to_one_on_triple_dupack():
    cc = Tahoe(max_cwnd=100, init_cwnd=20, ssthresh=10)
    assert not cc.on_dup_ack(1, 20) and not cc.on_dup_ack(2, 20)
    assert cc.on_dup_ack(3, 20)
    assert cc.cwnd == 1 and cc.ssthresh == 10


def test_reno_fast_recovery():
    cc = Reno(max_cwnd=100, init_cwnd=20, ssthresh=10)
    cc.on_dup_ack(1, 20); cc.on_dup_ack(2, 20)
    assert cc.on_dup_ack(3, 20)
    assert cc.state == FAST_RECOVERY and cc.ssthresh == 10 and cc.cwnd == 13
    cc.on_dup_ack(4, 20)
    assert cc.cwnd == 14  # inflation
    cc.on_new_ack(1)
    assert cc.cwnd == 10 and cc.state == CONG_AVOID  # deflate, no slow start


def test_timeout_always_restarts_slow_start():
    for name in ("tahoe", "reno"):
        cc = make_congestion_control(name, max_cwnd=100, ssthresh=64)
        cc.cwnd = 30
        cc.on_timeout(30)
        assert cc.cwnd == 1 and cc.ssthresh == 15 and cc.state == SLOW_START


def test_cwnd_capped_by_window():
    cc = Tahoe(max_cwnd=8, ssthresh=100)
    cc.on_new_ack(50)
    assert cc.cwnd == 8
