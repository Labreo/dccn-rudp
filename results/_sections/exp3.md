## Experiment 3 - Congestion control
Bottleneck 2 Mbit/s, base RTT 40 ms, drop-tail queue of 20 packets, no random loss: every loss here is a queue overflow, i.e. congestion. Bandwidth-delay product = 9.6 packets, so the 'pipe' holds about 30 packets before the queue overflows.

* A fixed window of 128 >> pipe size floods the queue: many drops, many retransmissions, low efficiency. Go-Back-N makes it far worse (every drop resends the window) - this is congestion collapse in miniature.
* Tahoe/Reno probe for bandwidth: slow start doubles cwnd each RTT, the first overflow sets ssthresh, then congestion avoidance adds 1 packet per RTT (AIMD saw-tooth). Tahoe falls back to cwnd = 1 on every loss, Reno halves it (fast recovery).

![cwnd](exp3_cwnd.png)
![rtt](exp3_rtt.png)

| run | goodput_kbps | utilisation | queue_drops | retransmissions | timeouts | fast_retransmits | efficiency | verified |
|---|---|---|---|---|---|---|---|---|
| SR, no CC, N=128 | 1426.4 | 71.3% | 1865 | 1865 | 261 | 0 | 44.6% | True |
| GBN, no CC, N=128 | 504.6 | 25.2% | 7089 | 8797 | 72 | 0 | 14.6% | True |
| SR + Tahoe | 1747.7 | 87.4% | 26 | 29 | 0 | 29 | 98.1% | True |
| SR + Reno | 1872.3 | 93.6% | 37 | 40 | 2 | 37 | 97.4% | True |
