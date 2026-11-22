# RUDP benchmark report

Last updated 2026-11-22 12:21 by `python -m rudp bench`. All transfers are real UDP transfers over 127.0.0.1 through the link emulator; every file was checked end-to-end with SHA-256 (column `verified`). The RTO floor is 100 ms (Linux uses 200 ms for real WAN RTTs; the emulated RTT here is only 20-40 ms).

## Experiment 1 - Goodput vs packet loss
Link: 4 Mbit/s bottleneck, 10 ms one-way delay, loss applied to data packets only, 128 KB file, 2 trial(s) per point.
Measured loss-free RTT = 27.3 ms, frame transmission time Tt = 2.09 ms, so 1 + 2a = RTT/Tt = 13.0. Stop-and-Wait can therefore use at most 1/(1+2a) = 7.7% of the link; a window of N >= 13 packets is needed to fill it.

![goodput vs loss](exp1_goodput_vs_loss.png)
![retransmissions vs loss](exp1_retx_vs_loss.png)

| protocol | loss | goodput_kbps | utilisation | retransmissions | timeouts | fast_retransmits | efficiency | verified |
|---|---|---|---|---|---|---|---|---|
| Stop-and-Wait | 0% | 300.2 | 7.5% | 0 | 0 | 0 | 100.0% | True |
| Stop-and-Wait | 1% | 295.2 | 7.4% | 0 | 0 | 0 | 100.0% | True |
| Stop-and-Wait | 2% | 276.0 | 6.9% | 3 | 3 | 0 | 97.7% | True |
| Stop-and-Wait | 5% | 238.0 | 5.9% | 8.5 | 8.5 | 0 | 93.8% | True |
| Stop-and-Wait | 10% | 223.8 | 5.6% | 11 | 11 | 0 | 92.2% | True |
| Stop-and-Wait | 15% | 160.1 | 4.0% | 23 | 23 | 0 | 84.8% | True |
| Stop-and-Wait | 20% | 115.1 | 2.9% | 41 | 41 | 0 | 75.8% | True |
| Go-Back-N (N=16) | 0% | 3613.0 | 90.3% | 0 | 0 | 0 | 100.0% | True |
| Go-Back-N (N=16) | 1% | 3623.7 | 90.6% | 0 | 0 | 0 | 100.0% | True |
| Go-Back-N (N=16) | 2% | 1637.5 | 40.9% | 48 | 3 | 0 | 73.3% | True |
| Go-Back-N (N=16) | 5% | 954.6 | 23.9% | 96 | 6.5 | 0 | 58.0% | True |
| Go-Back-N (N=16) | 10% | 432.3 | 10.8% | 214.5 | 16 | 0 | 38.4% | True |
| Go-Back-N (N=16) | 15% | 293.5 | 7.3% | 343 | 23 | 0 | 27.6% | True |
| Go-Back-N (N=16) | 20% | 164.9 | 4.1% | 557 | 36 | 0 | 18.7% | True |
| Selective Repeat (N=16) | 0% | 3621.2 | 90.5% | 0 | 0 | 0 | 100.0% | True |
| Selective Repeat (N=16) | 1% | 3624.2 | 90.6% | 0 | 0 | 0 | 100.0% | True |
| Selective Repeat (N=16) | 2% | 1961.1 | 49.0% | 3 | 3 | 0 | 97.7% | True |
| Selective Repeat (N=16) | 5% | 1334.0 | 33.4% | 8.5 | 7.5 | 0 | 93.8% | True |
| Selective Repeat (N=16) | 10% | 1195.0 | 29.9% | 11 | 9.5 | 0 | 92.2% | True |
| Selective Repeat (N=16) | 15% | 845.1 | 21.1% | 23 | 11 | 0 | 84.8% | True |
| Selective Repeat (N=16) | 20% | 451.7 | 11.3% | 41 | 22 | 0 | 75.8% | True |
| GBN + Reno (N<=16) | 0% | 2883.8 | 72.1% | 0 | 0 | 0 | 100.0% | True |
| GBN + Reno (N<=16) | 1% | 2879.1 | 72.0% | 0 | 0 | 0 | 100.0% | True |
| GBN + Reno (N<=16) | 2% | 2038.8 | 51.0% | 39 | 0 | 3 | 76.9% | True |
| GBN + Reno (N<=16) | 5% | 1091.2 | 27.3% | 63.5 | 2 | 6 | 67.0% | True |
| GBN + Reno (N<=16) | 10% | 941.0 | 23.5% | 77 | 1.5 | 10 | 62.6% | True |
| GBN + Reno (N<=16) | 15% | 239.8 | 6.0% | 91 | 18.5 | 5 | 59.3% | True |
| GBN + Reno (N<=16) | 20% | 131.0 | 3.3% | 99 | 36.5 | 4.5 | 56.4% | True |
| SR + Reno (N<=16) | 0% | 2849.7 | 71.2% | 0 | 0 | 0 | 100.0% | True |
| SR + Reno (N<=16) | 1% | 2888.4 | 72.2% | 0 | 0 | 0 | 100.0% | True |
| SR + Reno (N<=16) | 2% | 2025.6 | 50.6% | 3 | 0 | 3 | 97.7% | True |
| SR + Reno (N<=16) | 5% | 1167.5 | 29.2% | 8.5 | 1 | 7.5 | 93.8% | True |
| SR + Reno (N<=16) | 10% | 839.8 | 21.0% | 11.5 | 3 | 8.5 | 91.9% | True |
| SR + Reno (N<=16) | 15% | 495.0 | 12.4% | 23 | 10.5 | 11 | 84.8% | True |
| SR + Reno (N<=16) | 20% | 172.3 | 4.3% | 41 | 33.5 | 7.5 | 75.8% | True |

## Experiment 2 - Sliding window size
Same link, 2% loss, 256 KB file, 3 trial(s) per point (every N uses the same link random seeds, so all points face the same loss pattern). Goodput rises roughly linearly with N until the window covers the bandwidth-delay product, then flattens at the link rate. Go-Back-N wastes more and more bandwidth as N grows because one loss forces the whole window to be resent; Selective Repeat resends only the lost packet, so its efficiency stays near (1-p).

![goodput vs window](exp2_goodput_vs_window.png)
![efficiency vs window](exp2_efficiency_vs_window.png)

| protocol | window | goodput_kbps | retransmissions | timeouts | efficiency | verified |
|---|---|---|---|---|---|---|
| Go-Back-N | 1 | 274.6 | 5 | 5 | 98.1% | True |
| Go-Back-N | 2 | 514.5 | 10 | 5 | 96.2% | True |
| Go-Back-N | 4 | 933.9 | 20 | 5 | 92.8% | True |
| Go-Back-N | 8 | 1431.5 | 44.333333333333336 | 5.666666666666667 | 85.3% | True |
| Go-Back-N | 12 | 1671.4 | 67.33333333333333 | 5.666666666666667 | 79.3% | True |
| Go-Back-N | 16 | 1556.9 | 101.33333333333333 | 6.333333333333333 | 72.2% | True |
| Go-Back-N | 24 | 1828.5 | 113.33333333333333 | 5 | 70.2% | True |
| Go-Back-N | 32 | 1622.4 | 171 | 6 | 60.7% | True |
| Go-Back-N | 48 | 1502.0 | 297.6666666666667 | 6.666666666666667 | 46.6% | True |
| Go-Back-N | 64 | 844.4 | 541.3333333333334 | 9.333333333333334 | 32.9% | True |
| Selective Repeat | 1 | 273.7 | 5 | 5 | 98.1% | True |
| Selective Repeat | 2 | 521.0 | 5 | 5 | 98.1% | True |
| Selective Repeat | 4 | 970.9 | 5 | 5 | 98.1% | True |
| Selective Repeat | 8 | 1600.5 | 5 | 5 | 98.1% | True |
| Selective Repeat | 12 | 2017.8 | 5 | 5 | 98.1% | True |
| Selective Repeat | 16 | 2044.4 | 5 | 5 | 98.1% | True |
| Selective Repeat | 24 | 2796.2 | 5 | 5 | 98.1% | True |
| Selective Repeat | 32 | 3134.6 | 5 | 5 | 98.1% | True |
| Selective Repeat | 48 | 3253.1 | 5.333333333333333 | 5 | 98.0% | True |
| Selective Repeat | 64 | 2904.9 | 5 | 4.333333333333333 | 98.1% | True |

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

## Experiment 4 - Error detection: CRC-32 vs Internet checksum
20000 random 64-byte frames per error pattern, both codes computed with the project's own implementations. CRC-32 (generator of degree 32) detects all single, double and odd-numbered bit errors and every burst of length <= 32; longer bursts slip through with probability about 2^-32. The Internet checksum is a plain sum, so it cannot see re-ordered 16-bit words or errors that cancel out in the sum.

![checksum](exp4_checksum.png)

| error_pattern | trials | crc32_undetected | inet16_undetected |
|---|---|---|---|
| 1-bit | 20000 | 0 | 0 |
| 2-bit | 20000 | 0 | 646 |
| 3-bit (odd) | 20000 | 0 | 67 |
| burst <= 16 | 20000 | 0 | 0 |
| burst 17-32 | 20000 | 0 | 0 |
| burst 33-64 | 20000 | 0 | 1 |
| random 8-bit | 20000 | 0 | 3 |
| 16-bit word swap | 20000 | 0 | 20000 |
| +1/-1 in two words | 20000 | 0 | 20000 |

## Experiment 5 - Why the window must be smaller than the sequence space
Small sequence numbers (m bits) on a link with 10% data loss and 50% ACK loss. When the window breaks the textbook limit, a retransmitted *old* packet carries the same sequence number as a *new* one the receiver is waiting for; the receiver accepts the wrong data and only the end-to-end SHA-256 check catches it ('corrupted'). 'stalled' means the sender and receiver lost agreement on the window entirely and the transfer was aborted.

| protocol | seq_bits | seq_space | window | rule | correct | corrupted | stalled |
|---|---|---|---|---|---|---|---|
| GBN | 2 | 4 | 3 | safe: N = 2^m - 1 | 6 | 0 | 0 |
| GBN | 2 | 4 | 4 | UNSAFE: N = 2^m | 2 | 0 | 4 |
| SR | 3 | 8 | 4 | safe: N = 2^(m-1) | 6 | 0 | 0 |
| SR | 3 | 8 | 5 | UNSAFE: N > 2^(m-1) | 1 | 5 | 0 |
| SR | 3 | 8 | 6 | UNSAFE: N > 2^(m-1) | 0 | 6 | 0 |

## Experiment 6 - Sequence / time diagram
Blue dots: first transmissions. Red crosses: retransmissions. Green: cumulative ACK. Vertical red lines: timeouts. Both runs use the same random seed for the link.

![seq-time](exp6_seq_time.png)
