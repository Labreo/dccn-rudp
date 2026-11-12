# Demo guide (5-10 minutes)

A short script for showing the project to the professor. The full details are
in [README.md](README.md) (section 3 is the long viva script, section 9 has
viva questions and answers).

## 1. Setup (do this before class)

Needs Python 3.10 or newer.

```bash
git clone https://github.com/Labreo/dccn-rudp.git
cd dccn-rudp
pip install -r requirements.txt
python -m pytest -q
```

The last command should end with `51 passed`. If `python` is not found, try
`python3` everywhere instead.

## 2. One-line explanation

"UDP can lose, corrupt, duplicate and reorder packets. We built our own
TCP-like protocol on top of plain UDP sockets: CRC-32 error detection,
Stop-and-Wait, Go-Back-N and Selective Repeat ARQ, RTT-based timeouts and
TCP Tahoe/Reno congestion control. Files arrive byte-identical, checked with
SHA-256, even over a link that we deliberately damage."

## 3. Live demo in the browser (main part)

```bash
python -m rudp viz
```

It opens http://localhost:8765. Click these scenarios in order, then
**Run transfer**. Each one shows a "what to watch" note on the page.

| Click | Point out |
|---|---|
| **Go-Back-N** | A packet is lost (red ✗). The receiver discards the packets after it, the timer runs out, and the sender goes back and resends the whole window. |
| **Selective Repeat** | Same losses as Go-Back-N. The receiver buffers out-of-order packets (purple) and only the lost packet is resent. Fewer retransmissions. |
| **Bit errors** | Orange packets have flipped bits. The receiver shows "CRC ✗", drops them, and the timeout recovers them. |
| **TCP Reno** | The cwnd chart: slow start doubles cwnd, then on loss it halves (AIMD saw-tooth). |
| **Unsafe window** | Window too big for the sequence numbers (breaks N ≤ 2^(m-1)). The receiver accepts old packets as new (red STALE boxes) and the banner says **CORRUPTED**. Shows why the textbook window limit exists. |

Top row = sender, bottom row = receiver, the frames are the sliding windows,
the bar under a sender box is its retransmission timer.

## 4. If there is more time

```bash
python -m rudp crc 1101011011 10011
```

CRC long division exactly as on paper (remainder `1110`).

```bash
python -m rudp demo --proto sr --cc reno --window 16 --packets 60 --loss 0.05
```

Coloured terminal log of every send, loss, ACK and cwnd change.

Then open `results/REPORT.md` (or the graphs in `results/`) to show measured
results vs theory:

* Stop-and-Wait measured 7.4% utilisation; the formula 1/(1+2a) predicts 7.6%.
* Sliding windows gave 12x the throughput of Stop-and-Wait.
* At 10% loss, Selective Repeat resent 11 packets, Go-Back-N 214.
* With Reno, the sender used 95% of a 2 Mbit/s bottleneck; without congestion
  control, Go-Back-N used 25%.
* CRC-32 caught every injected error; the Internet checksum missed all
  swapped-word errors.

## 5. Likely questions

**Why not just use TCP?** The point is to implement what TCP does inside the
kernel and measure it. QUIC (HTTP/3) does the same thing: reliability over UDP.

**What happens to a corrupted packet?** The CRC fails, the receiver drops it
without an ACK, so it looks like a loss and the timer resends it.

**GBN vs SR?** GBN has one timer and discards out-of-order packets, so one
loss resends the whole window. SR has a timer per packet and buffers, so only
lost packets are resent, but it needs N ≤ 2^(m-1) instead of 2^m - 1.

**How is the timeout chosen?** RFC 6298: SRTT and RTTVAR from measured RTTs,
RTO = SRTT + 4·RTTVAR, Karn's rule, and the RTO doubles after each timeout.

**Is the network real?** Yes, real UDP sockets. Our link emulator adds loss,
bit errors, delay and a bandwidth limit, because a LAN almost never loses
packets.

## If something goes wrong

* `Address already in use` for viz: run `python -m rudp viz --port 8766`.
* The browser does not open: open http://localhost:8765 yourself.
* `matplotlib` errors: only the graphs need it; `viz`, `demo` and `crc` work
  without it.
