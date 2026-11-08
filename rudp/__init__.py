"""RUDP - a reliable, TCP-like transport protocol built on top of UDP.

DCCN mini project (CMP-302 / CMP-303).

Layers implemented here, bottom to top:

    checksum.py    error detection: CRC-32 (table + bitwise), Internet checksum
    packet.py      framing: fixed 22-byte header + payload
    channel.py     an unreliable "physical link" emulator (loss, corruption,
                   duplication, delay, jitter/reordering, bottleneck queue)
    rtt.py         adaptive retransmission timeout (Jacobson/Karels, Karn)
    congestion.py  congestion control: none / TCP Tahoe / TCP Reno
    sender.py      ARQ senders: Stop-and-Wait, Go-Back-N, Selective Repeat
    receiver.py    matching receivers + connection management
    local.py       run a sender and receiver inside one process (experiments)
    experiments.py benchmark suite that produces CSVs, plots and a report
"""

__version__ = "1.0.0"
