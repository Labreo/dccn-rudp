## Experiment 1 - Goodput vs packet loss
Link: 4 Mbit/s bottleneck, 10 ms one-way delay, loss applied to data packets only, 128 KB file, 2 trial(s) per point.
Measured loss-free RTT = 27.6 ms, frame transmission time Tt = 2.09 ms, so 1 + 2a = RTT/Tt = 13.2. Stop-and-Wait can therefore use at most 1/(1+2a) = 7.6% of the link; a window of N >= 13 packets is needed to fill it.

![goodput vs loss](exp1_goodput_vs_loss.png)
![retransmissions vs loss](exp1_retx_vs_loss.png)

| protocol | loss | goodput_kbps | utilisation | retransmissions | timeouts | fast_retransmits | efficiency | verified |
|---|---|---|---|---|---|---|---|---|
| Stop-and-Wait | 0% | 295.3 | 7.4% | 0 | 0 | 0 | 100.0% | True |
| Stop-and-Wait | 1% | 294.0 | 7.3% | 0 | 0 | 0 | 100.0% | True |
| Stop-and-Wait | 2% | 272.1 | 6.8% | 3 | 3 | 0 | 97.7% | True |
| Stop-and-Wait | 5% | 235.0 | 5.9% | 8.5 | 8.5 | 0 | 93.8% | True |
| Stop-and-Wait | 10% | 221.4 | 5.5% | 11 | 11 | 0 | 92.2% | True |
| Stop-and-Wait | 15% | 160.1 | 4.0% | 23 | 23 | 0 | 84.8% | True |
| Stop-and-Wait | 20% | 114.3 | 2.9% | 41 | 41 | 0 | 75.8% | True |
| Go-Back-N (N=16) | 0% | 3627.4 | 90.7% | 0 | 0 | 0 | 100.0% | True |
| Go-Back-N (N=16) | 1% | 3624.8 | 90.6% | 0 | 0 | 0 | 100.0% | True |
| Go-Back-N (N=16) | 2% | 1611.4 | 40.3% | 48 | 3 | 0 | 73.3% | True |
| Go-Back-N (N=16) | 5% | 960.7 | 24.0% | 96 | 6.5 | 0 | 58.0% | True |
| Go-Back-N (N=16) | 10% | 430.6 | 10.8% | 214.5 | 16 | 0 | 38.4% | True |
| Go-Back-N (N=16) | 15% | 293.3 | 7.3% | 343 | 23 | 0 | 27.6% | True |
| Go-Back-N (N=16) | 20% | 166.6 | 4.2% | 557 | 36 | 0 | 18.7% | True |
| Selective Repeat (N=16) | 0% | 3620.9 | 90.5% | 0 | 0 | 0 | 100.0% | True |
| Selective Repeat (N=16) | 1% | 3620.4 | 90.5% | 0 | 0 | 0 | 100.0% | True |
| Selective Repeat (N=16) | 2% | 1955.2 | 48.9% | 3 | 3 | 0 | 97.7% | True |
| Selective Repeat (N=16) | 5% | 1342.7 | 33.6% | 8.5 | 7.5 | 0 | 93.8% | True |
| Selective Repeat (N=16) | 10% | 1228.7 | 30.7% | 11 | 8 | 0 | 92.2% | True |
| Selective Repeat (N=16) | 15% | 850.6 | 21.3% | 23 | 10.5 | 0 | 84.8% | True |
| Selective Repeat (N=16) | 20% | 478.8 | 12.0% | 41 | 19 | 0 | 75.8% | True |
| GBN + Reno (N<=16) | 0% | 2905.3 | 72.6% | 0 | 0 | 0 | 100.0% | True |
| GBN + Reno (N<=16) | 1% | 2838.4 | 71.0% | 0 | 0 | 0 | 100.0% | True |
| GBN + Reno (N<=16) | 2% | 2020.9 | 50.5% | 39 | 0 | 3 | 76.9% | True |
| GBN + Reno (N<=16) | 5% | 1088.4 | 27.2% | 63.5 | 2 | 6 | 67.0% | True |
| GBN + Reno (N<=16) | 10% | 933.6 | 23.3% | 77 | 1.5 | 10 | 62.6% | True |
| GBN + Reno (N<=16) | 15% | 238.6 | 6.0% | 91 | 18.5 | 5 | 59.3% | True |
| GBN + Reno (N<=16) | 20% | 130.9 | 3.3% | 99 | 36.5 | 4.5 | 56.4% | True |
| SR + Reno (N<=16) | 0% | 2878.8 | 72.0% | 0 | 0 | 0 | 100.0% | True |
| SR + Reno (N<=16) | 1% | 2899.0 | 72.5% | 0 | 0 | 0 | 100.0% | True |
| SR + Reno (N<=16) | 2% | 1788.9 | 44.7% | 3 | 0 | 3 | 97.7% | True |
| SR + Reno (N<=16) | 5% | 961.5 | 24.0% | 8.5 | 2 | 6.5 | 93.8% | True |
| SR + Reno (N<=16) | 10% | 791.4 | 19.8% | 11.5 | 4.5 | 7 | 91.9% | True |
| SR + Reno (N<=16) | 15% | 450.6 | 11.3% | 23 | 12.5 | 10 | 84.8% | True |
| SR + Reno (N<=16) | 20% | 169.8 | 4.2% | 41 | 33.5 | 7.5 | 75.8% | True |
