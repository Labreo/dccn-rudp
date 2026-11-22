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
