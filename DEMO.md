# Presentation guide

How to show the project to the professor in about 10 minutes. The focus is the
**syllabus concepts** and proof that the system **works**; nobody needs to open
the code. The full written report is in [report/](report/).

---

## 1. The night before (on the laptop you will present from)

Needs Python 3.10 or newer (`python --version`). On Windows use `python`, on
macOS/Linux you may need `python3` everywhere below.

```bash
git clone https://github.com/Labreo/dccn-rudp.git
cd dccn-rudp
pip install -r requirements.txt
python -m pytest -q
```

The last line must say **`51 passed`**. Then do one full practice run of
section 3 below. Nothing needs the internet once this is done.

On the day: charge the laptop, close other apps, open these in advance:

1. a terminal in the `dccn-rudp` folder
2. the visualizer: `python -m rudp viz` (it opens http://localhost:8765)
3. the report PDF `report/RUDP_Mini_Project_Report.pdf` (graphs are in Chapter 7)

---

## 2. Opening (30 seconds)

> "UDP gives no guarantee: packets can be lost, corrupted, duplicated or
> arrive out of order. We built our own reliable transport protocol, like a
> small TCP, on top of plain UDP sockets. Everything from the syllabus is
> implemented by us: framing with CRC-32, Stop-and-Wait, Go-Back-N and
> Selective Repeat ARQ, sliding windows, sequence numbers, RTT-based timers
> and TCP congestion control. To test it we built a link emulator that
> deliberately loses and damages packets. Every file is checked with SHA-256
> at the end, so we can prove it arrived exactly right."

---

## 3. The demo, one concept at a time

In the visualizer: **top row = sender**, **bottom row = receiver**, the blue
frame is the **send window**, the dashed frame the **receive window**, a red ✗
is a **lost packet**, the bar under a sender box is its **retransmission
timer**. Click a scenario button; it starts by itself. Each one shows a "what to
watch" note.

### Step 1: Error detection with CRC (Unit 3, Lab) – terminal

```bash
python -m rudp crc 1101011011 10011
```

Shows long division exactly as on paper.

**Say:** "The sender appends r zero bits (r = degree of the generator, here 4),
divides by the generator using XOR, and sends the remainder `1110` as the CRC.
The receiver divides the whole frame `11010110111110` by the same generator;
remainder zero means no error. Our packets use the 32-bit generator CRC-32."

### Step 2: Stop-and-Wait (Unit 3) – click **Stop-and-Wait**

**Point at:** only one packet is ever in flight; sequence numbers go 0, 1, 0, 1.
After a loss the sender waits for the whole timeout.

**Say:** "One-bit sequence numbers are enough because only one packet is
outstanding. Utilisation is 1/(1+2a), where a = propagation time ÷ transmission
time. In our measurement it was 7.5% against 7.7% predicted by the formula."

### Step 3: Go-Back-N (Unit 3) – click **Go-Back-N**

**Point at:** a packet is lost (red ✗). The receiver **discards** every later
packet (receive window = 1) and keeps sending the same ACK. One timer runs out
and the sender **goes back** and resends the whole window.

**Say:** "Sliding window of N = 4 packets, cumulative ACKs, one timer for the
oldest unacknowledged packet. Simple receiver, but one loss costs a whole
window of retransmissions."

### Step 4: Selective Repeat (Unit 3) – click **Selective Repeat**

Same link settings and random seed as Go-Back-N, so the two can be compared directly (in our run: GBN retransmitted 24 packets, SR 9).

**Point at:** out-of-order packets turn **purple**: the receiver **buffers**
them. Each packet has its own timer and only the lost one is resent. Compare
the "Retransmitted" number with Go-Back-N.

**Say:** "Selective ACKs and a timer per packet. Fewer retransmissions, but the
receiver needs a buffer and the window must be at most half the sequence
space."

### Step 5: Corrupted frames (Unit 3) – click **Bit errors (CRC)**

**Point at:** orange packets have flipped bits; the receiver shows "CRC ✗",
throws them away and sends no ACK; the sender's timer recovers them.

**Say:** "A corrupted frame is treated exactly like a lost one: detect with
CRC, discard, and let ARQ retransmit."

### Step 6: TCP congestion control (Unit 4) – click **TCP Reno**

**Point at the cwnd chart:** it doubles every round trip (**slow start**:
1, 2, 4, 8 ...). When **3 duplicate ACKs** arrive the lost packet is resent at
once (**fast retransmit**), ssthresh becomes half of what was in flight and
cwnd drops (**fast recovery**), then grows by about one packet per round trip
(**additive increase**). The dashed line is ssthresh.

**Say:** "This is AIMD: additive increase, multiplicative decrease. It stops a
sender from flooding the router queue. In our experiment, a fixed big window
used only 25–71% of a 2 Mbit/s bottleneck; with Reno it used 94%."

### Step 7: Why the window size is limited (Unit 3) – click **Unsafe window**

3-bit sequence numbers (0–7) with N = 6, which breaks the rule
N ≤ 2^(m−1) = 4 for Selective Repeat.

**Point at:** red boxes on the receiver row = **stale data accepted**, and the
banner **"File CORRUPTED"**.

**Say:** "When ACKs are lost, the sender retransmits an old packet whose
sequence number is the same as a new packet the receiver is now expecting. The
receiver cannot tell them apart and accepts wrong data. Every packet passed its
CRC; only our end-to-end SHA-256 check caught it. With N = 4 it always works.
For Go-Back-N the limit is N ≤ 2^m − 1."

### Step 8 (if time): measured results – report PDF, Chapter 7

* Goodput vs loss: Selective Repeat beats Go-Back-N at every loss rate; at 10%
  loss GBN resent 214 packets for a 128-packet file, SR 11.
* Goodput vs window: grows like N/(1+2a) until the link is full; GBN gets
  worse for large N because each loss resends N packets.
* Congestion window saw-tooth (Figure 7.13).
* CRC-32 caught every injected error; the 16-bit Internet checksum missed
  every swapped-word error.

### Step 9 (optional): a real file between two laptops

Both laptops on the same Wi-Fi or phone hotspot.

```bash
python -m rudp recv --port 9000                       # laptop B: prints its IP
python -m rudp send somefile.pdf --to <B's IP>:9000 --proto sr --window 32 --cc reno --loss 0.05
```

The receiver ends with `integrity : OK - SHA-256 matches`. College Wi-Fi often
blocks laptop-to-laptop traffic; use a phone hotspot if it does not connect.

---

## 4. Concepts and formulas to have ready

| Concept | Key point |
|---|---|
| Transmission delay | Tt = L / R (frame length ÷ bandwidth) |
| Propagation delay | Tp = distance ÷ signal speed (our emulator: `--delay`) |
| a | a = Tp / Tt |
| Stop-and-Wait utilisation | U = 1 / (1 + 2a) |
| Sliding-window utilisation | U = min(1, N / (1 + 2a)); the pipe is full when N ≥ 1 + 2a |
| Bandwidth-delay product | bits "in the pipe" = bandwidth × RTT |
| Sequence space | m bits → numbers 0 … 2^m − 1 |
| Window limits | Go-Back-N: N ≤ 2^m − 1. Selective Repeat: N ≤ 2^(m−1) |
| CRC | append r zeros, XOR-divide by the (r+1)-bit generator, send remainder; receiver remainder 0 = OK |
| Internet checksum | 16-bit one's-complement sum; cannot detect reordered words |
| RTO (RFC 6298) | SRTT = 7/8·SRTT + 1/8·R; RTTVAR = 3/4·RTTVAR + 1/4·\|SRTT − R\|; RTO = SRTT + 4·RTTVAR |
| Karn's rule | no RTT sample from a retransmitted packet; the RTO doubles after each timeout |
| Slow start | cwnd + 1 per ACK, so it doubles every RTT, until ssthresh |
| Congestion avoidance | cwnd + 1/cwnd per ACK, so +1 per RTT (additive increase) |
| 3 duplicate ACKs | Tahoe: ssthresh = flight/2, cwnd = 1. Reno: ssthresh = flight/2, cwnd = ssthresh + 3 (fast recovery) |
| Timeout | ssthresh = flight/2, cwnd = 1, slow start again |
| Flow vs congestion control | flow control protects the **receiver** (rwnd); congestion control protects the **network** (cwnd). Window = min(N, cwnd, rwnd) |
| 3-way handshake | SYN → SYN-ACK → ACK; teardown FIN → FIN-ACK; TIME_WAIT answers a repeated FIN |

---

## 5. Questions the professor may ask

**Why build this on UDP instead of using TCP?**
To implement ourselves what TCP does inside the operating system and to see
and measure each mechanism. Real protocols do the same: QUIC (used by HTTP/3)
is reliable transport built on UDP; TFTP uses Stop-and-Wait over UDP.

**How do you know the file arrived correctly?**
Three levels: CRC-32 on every packet, a SHA-256 hash of the whole file sent in
the FIN and checked by the receiver, and in testing we compare the files byte
by byte. All 51 automated tests pass.

**Is the network real or simulated?**
Real UDP sockets. A LAN almost never loses packets, so our link emulator
deliberately drops, corrupts, duplicates, delays and reorders packets, with
settings like `--loss 0.1`. The same protocol works between two laptops.

**What happens when a packet is corrupted?**
The CRC check fails, the receiver discards it and sends no ACK, so the sender
times out (or sees duplicate ACKs) and retransmits.

**What happens when an ACK is lost?**
ACKs are cumulative, so a later ACK confirms the earlier packets too. Only if
every ACK for a window is lost does the sender time out and resend; the
receiver recognises the duplicate and just ACKs it again.

**Go-Back-N vs Selective Repeat?**
GBN: receiver window 1, cumulative ACKs, one timer, resend the whole window.
SR: receiver buffers, selective ACKs, a timer per packet, resend only the lost
packet. SR needs more buffer and a smaller window for the same sequence bits.

**Why is the SR window limited to half the sequence space?**
The sender's window and the receiver's window must never overlap modulo 2^m.
Otherwise, if ACKs are lost, an old retransmission looks like a new packet.
The Unsafe window demo shows exactly this.

**How is the timeout chosen?**
From measured round-trip times (RFC 6298, Jacobson's algorithm): a smoothed
average plus four times the variation. Retransmitted packets are not measured
(Karn's rule), and after each timeout the RTO doubles (exponential back-off).

**What is the difference between flow control and congestion control?**
Flow control: the receiver advertises how much buffer it has (rwnd), so the
sender does not overflow the receiver. Congestion control: the sender limits
itself (cwnd) so it does not overflow routers in the network.

**Tahoe vs Reno?**
Both use slow start and AIMD. On three duplicate ACKs, Tahoe drops cwnd to 1;
Reno halves it and does fast recovery, so it keeps sending.

**Why fast retransmit after 3 duplicate ACKs and not 1?**
One or two duplicate ACKs can be caused by reordering; three is strong evidence
that the packet was really lost.

**CRC vs checksum?**
CRC is polynomial division and detects all burst errors up to its length
(32 bits for CRC-32). The Internet checksum is just a sum, so swapping two
16-bit words gives the same value. Our experiment: CRC-32 missed 0 errors,
the checksum missed 100% of swapped-word errors.

**What are the limitations?**
One file per connection, windows counted in packets not bytes, no encryption,
and Python limits speed to tens of Mbit/s. Possible extensions: TCP CUBIC/BBR,
forward error correction, several connections sharing a link.

---

## 6. If something goes wrong

| Problem | Fix |
|---|---|
| `python` not found | use `python3` (macOS/Linux) or `py` (Windows) |
| Port 8765 busy | it picks the next free port automatically; read the address it prints |
| Browser does not open | open the printed address (http://localhost:8765) yourself |
| A scenario is too slow | press Stop, lower "One-way delay ms" (e.g. 300), Run again |
| Two laptops cannot connect | same network? use a phone hotspot; allow Python in the firewall prompt |
| Anything else | show the screenshots in Chapter 6 and 7 of the report PDF |
