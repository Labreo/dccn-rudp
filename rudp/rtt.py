"""Adaptive retransmission timeout (Transport layer, Unit 4).

Implements RFC 6298 (the algorithm every TCP uses):

    first sample R:   SRTT = R,  RTTVAR = R/2
    later samples R:  RTTVAR = (1 - beta) * RTTVAR + beta * |SRTT - R|
                      SRTT   = (1 - alpha) * SRTT  + alpha * R
                      RTO    = SRTT + max(G, K * RTTVAR)
    alpha = 1/8, beta = 1/4, K = 4  (Jacobson / Karels)

* Karn's algorithm: never take an RTT sample from a retransmitted packet,
  because we cannot tell which copy the ACK belongs to. (The senders enforce
  this by only calling ``sample`` for packets sent exactly once.)
* Exponential back-off: every timeout doubles the RTO until a fresh valid
  sample arrives.
"""

from __future__ import annotations


class RTOEstimator:
    def __init__(self, initial: float = 1.0, min_rto: float = 0.2, max_rto: float = 60.0,
                 alpha: float = 1 / 8, beta: float = 1 / 4, k: float = 4.0,
                 granularity: float = 0.001):
        self.alpha, self.beta, self.k, self.g = alpha, beta, k, granularity
        self.min_rto, self.max_rto = min_rto, max_rto
        self.srtt: float | None = None
        self.rttvar: float | None = None
        self.rto = max(min_rto, initial)
        self.samples = 0

    def sample(self, rtt: float) -> float:
        if rtt < 0:
            return self.rto
        if self.srtt is None:
            self.srtt = rtt
            self.rttvar = rtt / 2
        else:
            self.rttvar = (1 - self.beta) * self.rttvar + self.beta * abs(self.srtt - rtt)
            self.srtt = (1 - self.alpha) * self.srtt + self.alpha * rtt
        self.samples += 1
        self.rto = self._clamp(self.srtt + max(self.g, self.k * self.rttvar))
        return self.rto

    def backoff(self) -> float:
        self.rto = self._clamp(self.rto * 2)
        return self.rto

    def reset_backoff(self) -> float:
        """Forward progress (new data ACKed): undo back-off, as Linux TCP does.

        Without this, Karn's rule can leave the RTO inflated for a long time
        when every packet in the window had to be retransmitted (Go-Back-N).
        """
        if self.srtt is not None:
            self.rto = self._clamp(self.srtt + max(self.g, self.k * self.rttvar))
        return self.rto

    def _clamp(self, v: float) -> float:
        return min(self.max_rto, max(self.min_rto, v))
