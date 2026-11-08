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
