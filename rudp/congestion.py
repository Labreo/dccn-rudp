"""Congestion control (Transport layer, Unit 4).

All windows are counted in packets (MSS-sized segments).

* ``none``  - fixed window. Textbook GBN / SR: the sender always keeps
              ``window`` packets in flight and has no fast retransmit.
* ``tahoe`` - TCP Tahoe (1988):
                slow start          cwnd += 1 per ACKed packet (doubles / RTT)
                congestion avoid.   cwnd += 1/cwnd per ACKed packet (+1 / RTT)
                3 duplicate ACKs    ssthresh = flight/2, cwnd = 1, fast retransmit
                timeout             ssthresh = flight/2, cwnd = 1
* ``reno``  - TCP Reno (1990): like Tahoe, but 3 duplicate ACKs enter
              *fast recovery*: ssthresh = flight/2, cwnd = ssthresh + 3,
              +1 per further dup ACK, and cwnd = ssthresh when a new ACK
              arrives (multiplicative decrease without restarting slow start).

The combination "+1 per RTT, halve on loss" is AIMD (additive increase,
multiplicative decrease), which produces the familiar saw-tooth.
"""

from __future__ import annotations

import math

SLOW_START = "slow-start"
CONG_AVOID = "cong-avoid"
FAST_RECOVERY = "fast-recovery"
FIXED = "fixed"


class NoCongestionControl:
    name = "none"

    def __init__(self, max_cwnd: float, **_):
        self.max_cwnd = max_cwnd
        self.cwnd = math.inf
        self.ssthresh = math.inf
        self.state = FIXED

    def window(self) -> float:
        return self.cwnd

    def on_new_ack(self, n: int) -> None:
        pass

    def on_dup_ack(self, count: int, flight: int) -> bool:
        return False  # textbook ARQ: only the timer triggers retransmission

    def on_timeout(self, flight: int) -> None:
        pass


class Tahoe(NoCongestionControl):
    name = "tahoe"

    def __init__(self, max_cwnd: float, init_cwnd: float = 1.0, ssthresh: float = 64.0):
        super().__init__(max_cwnd)
        self.cwnd = float(init_cwnd)
        self.ssthresh = float(ssthresh)
        self.state = SLOW_START

    def on_new_ack(self, n: int) -> None:
        for _ in range(n):
            if self.cwnd < self.ssthresh:
                self.cwnd += 1.0  # exponential growth
            else:
                self.cwnd += 1.0 / self.cwnd  # linear growth
        self.cwnd = min(self.cwnd, self.max_cwnd)
        self.state = SLOW_START if self.cwnd < self.ssthresh else CONG_AVOID

    def _halve(self, flight: int) -> None:
        self.ssthresh = max(flight / 2.0, 2.0)

    def on_dup_ack(self, count: int, flight: int) -> bool:
        if count == 3:
            self._halve(flight)
            self.cwnd = 1.0
            self.state = SLOW_START
            return True
        return False

    def on_timeout(self, flight: int) -> None:
        self._halve(flight)
        self.cwnd = 1.0
        self.state = SLOW_START


class Reno(Tahoe):
    name = "reno"

    def on_dup_ack(self, count: int, flight: int) -> bool:
        if count == 3 and self.state != FAST_RECOVERY:
            self._halve(flight)
            self.cwnd = self.ssthresh + 3  # 3 packets have left the network
            self.state = FAST_RECOVERY
            return True
        if self.state == FAST_RECOVERY:
            self.cwnd += 1.0  # window inflation: each dup ACK = one packet left
        return False

    def on_new_ack(self, n: int) -> None:
        if self.state == FAST_RECOVERY:
            self.cwnd = self.ssthresh  # deflate, go straight to cong. avoidance
            self.state = CONG_AVOID
            return
        super().on_new_ack(n)


ALGORITHMS = {"none": NoCongestionControl, "tahoe": Tahoe, "reno": Reno}


def make_congestion_control(name: str, max_cwnd: float, ssthresh: float = 64.0,
                            init_cwnd: float = 1.0):
    try:
        cls = ALGORITHMS[name]
    except KeyError:
        raise ValueError(f"unknown congestion control {name!r}; pick one of {list(ALGORITHMS)}")
    return cls(max_cwnd=max_cwnd, ssthresh=ssthresh, init_cwnd=init_cwnd)
