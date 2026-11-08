"""Benchmark suite: ``python -m rudp bench``.

Every experiment runs real transfers over 127.0.0.1 through the link
emulator, writes a CSV, draws a PNG and adds a section to REPORT.md.

    exp1  goodput vs packet-loss rate (SW, GBN, SR, with/without Reno)
    exp2  goodput vs window size N (GBN vs SR) - the sliding-window effect
    exp3  congestion control over a bottleneck (none vs Tahoe vs Reno)
    exp4  error-detection strength: CRC-32 vs Internet checksum
    exp5  sequence-number space: window limits 2^m-1 (GBN) and 2^(m-1) (SR)
    exp6  sequence/time diagrams for GBN vs SR
"""

from __future__ import annotations

import csv
import json
import os
import random
import statistics
import time
from dataclasses import replace

from .channel import LinkConfig
from .checksum import crc32, internet_checksum
from .local import run_local_transfer
from .packet import HEADER_LEN
from .sender import SenderConfig, TransferError

MSS = 1024
FRAME = MSS + HEADER_LEN
# The emulated RTT here is ~25 ms, so the RTO floor is scaled down from Linux's
# 200 ms (meant for real WAN RTTs) to 100 ms, i.e. still about 4 x RTT.
BENCH_MIN_RTO = 0.1


def _write_csv(path, rows):
    if not rows:
        return
    keys = list(rows[0].keys())
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)


def _md_table(rows, cols, fmt=None):
    fmt = fmt or {}
    out = ["| " + " | ".join(cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    for r in rows:
        cells = []
        for c in cols:
            v = r.get(c, "")
            cells.append(fmt[c](v) if c in fmt and v not in ("", None) else str(v))
        out.append("| " + " | ".join(cells) + " |")
    return "\n".join(out)


class Bench:
    def __init__(self, out_dir="results", quick=False, log=print):
        self.out = out_dir
        self.quick = quick
        self.say = log
        self.md: list[str] = []
        os.makedirs(out_dir, exist_ok=True)

    def p(self, name):
        return os.path.join(self.out, name)

    def transfer(self, data, cfg, link, ack_link=None, trials=1, seed=0):
        """Average several runs; returns dict of metrics."""
        res = []
        cfg = replace(cfg, min_rto=BENCH_MIN_RTO)
        for k in range(trials):
            l1 = replace(link, seed=seed * 1000 + k * 17 + 1)
            l2 = replace(ack_link or LinkConfig(delay_ms=link.delay_ms), seed=seed * 1000 + k * 17 + 2)
            try:
                s, r = run_local_transfer(data, cfg, l1, l2)
                res.append(s)
            except TransferError as e:
                self.say(f"      ! transfer failed: {e}")
        if not res:
            return None
        avg = lambda f: statistics.mean(f(s) for s in res)  # noqa: E731
        return {
            "goodput_kbps": avg(lambda s: s.goodput_kbps),
            "time_s": avg(lambda s: s.data_s),
            "retx": avg(lambda s: s.stats["retransmissions"]),
            "timeouts": avg(lambda s: s.stats["timeouts"]),
            "fast_retx": avg(lambda s: s.stats["fast_retransmits"]),
            "efficiency": avg(lambda s: s.efficiency),
            "srtt_ms": avg(lambda s: s.srtt_ms or 0),
            "verified": all(s.verified for s in res),
            "_last": res[-1],
        }

    # ------------------------------------------------------------- exp 1

    def exp1_loss(self):
        self.say("\n[exp1] goodput vs loss rate")
        from .plots import line_plot
        rate, delay = 4000.0, 10.0
        losses = [0, 0.02, 0.05, 0.1, 0.2] if self.quick else [0, 0.01, 0.02, 0.05, 0.1, 0.15, 0.2]
        trials = 1 if self.quick else 2
        data = os.urandom((64 if self.quick else 128) * MSS)
        configs = [
            ("Stop-and-Wait", SenderConfig(protocol="sw")),
            ("Go-Back-N (N=16)", SenderConfig(protocol="gbn", window=16)),
            ("Selective Repeat (N=16)", SenderConfig(protocol="sr", window=16)),
            ("GBN + Reno (N<=16)", SenderConfig(protocol="gbn", window=16, cc="reno")),
            ("SR + Reno (N<=16)", SenderConfig(protocol="sr", window=16, cc="reno")),
        ]
        rows, series, retx_series = [], {}, {}
        for label, cfg in configs:
            series[label], retx_series[label] = [], []
            for p in losses:
                link = LinkConfig(loss=p, delay_ms=delay, rate_kbps=rate, queue=200)
                m = self.transfer(data, cfg, link, trials=trials, seed=int(p * 1000))
                if m is None:
                    series[label].append(float("nan"))
                    retx_series[label].append(float("nan"))
                    continue
                self.say(f"   {label:<26} loss={p:4.0%}  {m['goodput_kbps']:8.1f} kbit/s"
                         f"  retx={m['retx']:6.1f}  timeouts={m['timeouts']:5.1f}  ok={m['verified']}")
                rows.append({"protocol": label, "loss": p, "goodput_kbps": round(m["goodput_kbps"], 1),
                             "utilisation": round(m["goodput_kbps"] / rate, 4),
                             "time_s": round(m["time_s"], 3), "retransmissions": m["retx"],
                             "timeouts": m["timeouts"], "fast_retransmits": m["fast_retx"],
                             "efficiency": round(m["efficiency"], 3), "srtt_ms": round(m["srtt_ms"], 1),
                             "verified": m["verified"]})
                series[label].append(m["goodput_kbps"])
                retx_series[label].append(m["retx"])
        _write_csv(self.p("exp1_loss_sweep.csv"), rows)

        # Theory. Cycle time for one frame ~ measured loss-free SW RTT.
        sw0 = next(r for r in rows if r["protocol"] == "Stop-and-Wait" and r["loss"] == 0)
        rtt = sw0["srtt_ms"] / 1000
        tt = FRAME * 8 / (rate * 1000)
        payload_rate = rate * MSS / FRAME
        a2 = rtt / tt  # = 1 + 2a
        xs = [i / 100 for i in range(0, int(max(losses) * 100) + 1)]
        rto = BENCH_MIN_RTO
        theory = {
            "Stop-and-Wait model: Tt / (RTT + p/(1-p)·RTO)":
                (xs, [payload_rate * tt / (rtt + p / (1 - p) * rto) for p in xs], 0),
            "SR textbook ideal, instant loss detection: (1-p)":
                (xs, [payload_rate * min(1, 16 / a2) * (1 - p) for p in xs], 2),
        }
        line_plot(self.p("exp1_goodput_vs_loss.png"), losses, series,
                  f"Goodput vs packet loss  (link {rate / 1000:.0f} Mbit/s, one-way delay {delay:.0f} ms)",
                  "packet loss probability (data direction)", "goodput (kbit/s)", theory=theory,
                  percent_x=True)
        line_plot(self.p("exp1_retx_vs_loss.png"), losses, retx_series,
                  f"Retransmissions needed for {len(data) // MSS} packets", "packet loss probability",
                  "retransmitted packets", percent_x=True)

        self.md += [
            "## Experiment 1 - Goodput vs packet loss",
            f"Link: {rate / 1000:.0f} Mbit/s bottleneck, {delay:.0f} ms one-way delay, loss applied to data "
            f"packets only, {len(data) // 1024} KB file, {trials} trial(s) per point.",
            f"Measured loss-free RTT = {rtt * 1000:.1f} ms, frame transmission time Tt = {tt * 1000:.2f} ms, "
            f"so 1 + 2a = RTT/Tt = {a2:.1f}. Stop-and-Wait can therefore use at most 1/(1+2a) = "
            f"{100 / a2:.1f}% of the link; a window of N >= {a2:.0f} packets is needed to fill it.",
            "",
            "![goodput vs loss](exp1_goodput_vs_loss.png)",
            "![retransmissions vs loss](exp1_retx_vs_loss.png)",
            "",
            _md_table(rows, ["protocol", "loss", "goodput_kbps", "utilisation", "retransmissions",
                             "timeouts", "fast_retransmits", "efficiency", "verified"],
                      {"loss": lambda v: f"{v:.0%}", "utilisation": lambda v: f"{v:.1%}",
                       "efficiency": lambda v: f"{v:.1%}"}),
            "",
        ]

    # ------------------------------------------------------------- exp 2

    def exp2_window(self):
        self.say("\n[exp2] goodput vs window size")
        from .plots import line_plot
        rate, delay, loss = 4000.0, 10.0, 0.02
        windows = [1, 2, 4, 8, 16, 32] if self.quick else [1, 2, 4, 8, 12, 16, 24, 32, 48, 64]
        data = os.urandom((96 if self.quick else 256) * MSS)
        trials = 1 if self.quick else 3
        rows, gp, eff = [], {}, {}
        for proto, label in (("gbn", "Go-Back-N"), ("sr", "Selective Repeat")):
            gp[label], eff[label] = [], []
            for n in windows:
                link = LinkConfig(loss=loss, delay_ms=delay, rate_kbps=rate, queue=200)
                m = self.transfer(data, SenderConfig(protocol=proto, window=n), link, trials=trials, seed=1)
                self.say(f"   {label:<17} N={n:<3} {m['goodput_kbps']:8.1f} kbit/s  retx={m['retx']:5.0f}"
                         f"  efficiency={m['efficiency']:.1%}")
                rows.append({"protocol": label, "window": n, "goodput_kbps": round(m["goodput_kbps"], 1),
                             "retransmissions": m["retx"], "timeouts": m["timeouts"],
                             "efficiency": round(m["efficiency"], 3), "verified": m["verified"]})
                gp[label].append(m["goodput_kbps"])
                eff[label].append(m["efficiency"] * 100)
        _write_csv(self.p("exp2_window_sweep.csv"), rows)
        line_plot(self.p("exp2_goodput_vs_window.png"), windows, gp,
                  f"Goodput vs window size N  (loss {loss:.0%}, {rate / 1000:.0f} Mbit/s, {delay:.0f} ms)",
                  "window size N (packets)", "goodput (kbit/s)")
        line_plot(self.p("exp2_efficiency_vs_window.png"), windows, eff,
                  "Transmission efficiency (useful / total packets sent)", "window size N (packets)",
                  "efficiency (%)")
        self.md += [
            "## Experiment 2 - Sliding window size",
            f"Same link, {loss:.0%} loss, {len(data) // 1024} KB file, {trials} trial(s) per point "
            "(every N uses the same link random seeds, so all points face the same loss pattern). Goodput rises roughly linearly with N until the window covers the "
            "bandwidth-delay product, then flattens at the link rate. Go-Back-N wastes more and more "
            "bandwidth as N grows because one loss forces the whole window to be resent; Selective "
            "Repeat resends only the lost packet, so its efficiency stays near (1-p).",
            "",
            "![goodput vs window](exp2_goodput_vs_window.png)",
            "![efficiency vs window](exp2_efficiency_vs_window.png)",
            "",
            _md_table(rows, ["protocol", "window", "goodput_kbps", "retransmissions", "timeouts",
                             "efficiency", "verified"], {"efficiency": lambda v: f"{v:.1%}"}),
            "",
        ]

    # ------------------------------------------------------------- exp 3

    def exp3_congestion(self):
        self.say("\n[exp3] congestion control over a bottleneck")
        from .plots import cwnd_plot, rtt_plot
        rate, delay, queue = 2000.0, 20.0, 20
        data = os.urandom((600 if self.quick else 1500) * MSS)
        tt = FRAME * 8 / (rate * 1000)
        bdp = 2 * delay / 1000 / tt
        runs = [
            ("SR, no CC, N=128", SenderConfig(protocol="sr", window=128, cc="none")),
            ("GBN, no CC, N=128", SenderConfig(protocol="gbn", window=128, cc="none")),
            ("SR + Tahoe", SenderConfig(protocol="sr", window=256, cc="tahoe")),
            ("SR + Reno", SenderConfig(protocol="sr", window=256, cc="reno")),
        ]
        rows, traces = [], {}
        for label, cfg in runs:
            link = LinkConfig(delay_ms=delay, rate_kbps=rate, queue=queue, seed=3)
            s, _ = run_local_transfer(data, cfg, link, LinkConfig(delay_ms=delay, seed=4))
            ch = s.stats["link_data"]
            self.say(f"   {label:<20} {s.goodput_kbps:7.1f} kbit/s  queue drops={ch['dropped_queue']:5}"
                     f"  retx={s.stats['retransmissions']:5}  efficiency={s.efficiency:.1%}"
                     f"  ok={s.verified}")
            rows.append({"run": label, "goodput_kbps": round(s.goodput_kbps, 1),
                         "utilisation": round(s.goodput_kbps / rate, 3),
                         "queue_drops": ch["dropped_queue"], "retransmissions": s.stats["retransmissions"],
                         "timeouts": s.stats["timeouts"], "fast_retransmits": s.stats["fast_retransmits"],
                         "efficiency": round(s.efficiency, 3), "srtt_ms": round(s.srtt_ms or 0, 1),
                         "verified": s.verified})
            if cfg.cc != "none":
                traces[label] = s.trace
            with open(self.p(f"exp3_trace_{cfg.protocol}_{cfg.cc}.json"), "w") as f:
                json.dump(s.to_dict(with_trace=True), f)
        _write_csv(self.p("exp3_congestion.csv"), rows)
        cwnd_plot(self.p("exp3_cwnd.png"), traces,
                  f"cwnd saw-tooth: {rate / 1000:.0f} Mbit/s bottleneck, RTT {2 * delay:.0f} ms, "
                  f"queue {queue} packets", queue_line=bdp + queue)
        if "SR + Reno" in traces:
            rtt_plot(self.p("exp3_rtt.png"), traces["SR + Reno"],
                     "RTT samples, SRTT and RTO during the Reno transfer (queueing delay grows with cwnd)")
        self.md += [
            "## Experiment 3 - Congestion control",
            f"Bottleneck {rate / 1000:.0f} Mbit/s, base RTT {2 * delay:.0f} ms, drop-tail queue of {queue} "
            f"packets, no random loss: every loss here is a queue overflow, i.e. congestion. "
            f"Bandwidth-delay product = {bdp:.1f} packets, so the 'pipe' holds about {bdp + queue:.0f} "
            "packets before the queue overflows.",
            "",
            "* A fixed window of 128 >> pipe size floods the queue: many drops, many retransmissions, "
            "low efficiency. Go-Back-N makes it far worse (every drop resends the window) - this is "
            "congestion collapse in miniature.",
            "* Tahoe/Reno probe for bandwidth: slow start doubles cwnd each RTT, the first overflow sets "
            "ssthresh, then congestion avoidance adds 1 packet per RTT (AIMD saw-tooth). Tahoe falls "
            "back to cwnd = 1 on every loss, Reno halves it (fast recovery).",
            "",
            "![cwnd](exp3_cwnd.png)",
            "![rtt](exp3_rtt.png)",
            "",
            _md_table(rows, ["run", "goodput_kbps", "utilisation", "queue_drops", "retransmissions",
                             "timeouts", "fast_retransmits", "efficiency", "verified"],
                      {"utilisation": lambda v: f"{v:.1%}", "efficiency": lambda v: f"{v:.1%}"}),
            "",
        ]

    # ------------------------------------------------------------- exp 4

    def exp4_checksum(self):
        self.say("\n[exp4] CRC-32 vs Internet checksum")
        from .plots import bar_plot
        rng = random.Random(42)
        trials = 4000 if self.quick else 20000
        size = 64

        def flip(buf, bits):
            for b in bits:
                buf[b // 8] ^= 1 << (7 - b % 8)

        def burst(buf, length):
            start = rng.randrange(size * 8 - length)
            inner = [start + k for k in range(1, length - 1) if rng.random() < 0.5]
            flip(buf, [start, start + length - 1] + inner)

        def word_swap(buf):
            while True:
                i, j = rng.sample(range(size // 2), 2)
                if buf[2 * i:2 * i + 2] != buf[2 * j:2 * j + 2]:
                    break
            buf[2 * i:2 * i + 2], buf[2 * j:2 * j + 2] = buf[2 * j:2 * j + 2], buf[2 * i:2 * i + 2]

        def compensating(buf):
            # +1 in one 16-bit word, -1 in another: the 1's-complement sum is unchanged
            while True:
                i, j = rng.sample(range(size // 2), 2)
                a = int.from_bytes(buf[2 * i:2 * i + 2], "big")
                b = int.from_bytes(buf[2 * j:2 * j + 2], "big")
                if a < 0xFFFE and b > 1:
                    break
            buf[2 * i:2 * i + 2] = (a + 1).to_bytes(2, "big")
            buf[2 * j:2 * j + 2] = (b - 1).to_bytes(2, "big")

        errors = {
            "1-bit": lambda b: flip(b, rng.sample(range(size * 8), 1)),
            "2-bit": lambda b: flip(b, rng.sample(range(size * 8), 2)),
            "3-bit (odd)": lambda b: flip(b, rng.sample(range(size * 8), 3)),
            "burst <= 16": lambda b: burst(b, rng.randint(2, 16)),
            "burst 17-32": lambda b: burst(b, rng.randint(17, 32)),
            "burst 33-64": lambda b: burst(b, rng.randint(33, 64)),
            "random 8-bit": lambda b: flip(b, rng.sample(range(size * 8), 8)),
            "16-bit word swap": word_swap,
            "+1/-1 in two words": compensating,
        }
        rows = []
        for name, inject in errors.items():
            miss = {"crc32": 0, "inet16": 0}
            for _ in range(trials):
                data = bytes(rng.getrandbits(8) for _ in range(size))
                c0, i0 = crc32(data), internet_checksum(data)
                buf = bytearray(data)
                inject(buf)
                if bytes(buf) == data:
                    continue
                miss["crc32"] += crc32(bytes(buf)) == c0
                miss["inet16"] += internet_checksum(bytes(buf)) == i0
            rows.append({"error_pattern": name, "trials": trials,
                         "crc32_undetected": miss["crc32"], "inet16_undetected": miss["inet16"],
                         "crc32_miss_rate": miss["crc32"] / trials, "inet16_miss_rate": miss["inet16"] / trials})
            self.say(f"   {name:<20} CRC-32 missed {miss['crc32']:6}   Internet checksum missed {miss['inet16']:6}"
                     f"   (of {trials})")
        _write_csv(self.p("exp4_checksum.csv"), rows)
        bar_plot(self.p("exp4_checksum.png"), [r["error_pattern"] for r in rows],
                 {"CRC-32": [r["crc32_miss_rate"] * 100 for r in rows],
                  "Internet checksum": [r["inet16_miss_rate"] * 100 for r in rows]},
                 f"Undetected errors (% of {trials} corrupted {size}-byte frames)", "undetected (%)")
        self.md += [
            "## Experiment 4 - Error detection: CRC-32 vs Internet checksum",
            f"{trials} random {size}-byte frames per error pattern, both codes computed with the "
            "project's own implementations. CRC-32 (generator of degree 32) detects all single, double "
            "and odd-numbered bit errors and every burst of length <= 32; longer bursts slip through with "
            "probability about 2^-32. The Internet checksum is a plain sum, so it cannot see re-ordered "
            "16-bit words or errors that cancel out in the sum.",
            "",
            "![checksum](exp4_checksum.png)",
            "",
            _md_table(rows, ["error_pattern", "trials", "crc32_undetected", "inet16_undetected"]),
            "",
        ]

    # ------------------------------------------------------------- exp 5

    def exp5_seqspace(self):
        self.say("\n[exp5] sequence-number space vs window size")
        cases = [
            ("gbn", 2, 3, "safe: N = 2^m - 1"),
            ("gbn", 2, 4, "UNSAFE: N = 2^m"),
            ("sr", 3, 4, "safe: N = 2^(m-1)"),
            ("sr", 3, 5, "UNSAFE: N > 2^(m-1)"),
            ("sr", 3, 6, "UNSAFE: N > 2^(m-1)"),
        ]
        trials = 3 if self.quick else 6
        data = os.urandom(64 * MSS)
        rows = []
        for proto, m, n, note in cases:
            ok = bad = err = 0
            for k in range(trials):
                cfg = SenderConfig(protocol=proto, window=n, seq_bits=m, unsafe=True, max_retries=8,
                                   min_rto=BENCH_MIN_RTO, max_rto=1.0)
                link = LinkConfig(loss=0.1, delay_ms=5, jitter_ms=1, seed=100 + k)
                ack = LinkConfig(loss=0.5, delay_ms=5, seed=200 + k)
                try:
                    s, r = run_local_transfer(data, cfg, link, ack)
                    if r is not None and r.ok:  # receiver's own SHA-256 verdict
                        ok += 1
                    else:
                        bad += 1
                except TransferError:
                    err += 1
            self.say(f"   {proto.upper():3} m={m} (seq 0..{2 ** m - 1}) N={n}: {ok} correct, {bad} CORRUPTED,"
                     f" {err} stalled  [{note}]")
            rows.append({"protocol": proto.upper(), "seq_bits": m, "seq_space": 2 ** m, "window": n,
                         "rule": note, "correct": ok, "corrupted": bad, "stalled": err})
        _write_csv(self.p("exp5_seqspace.csv"), rows)
        self.md += [
            "## Experiment 5 - Why the window must be smaller than the sequence space",
            "Small sequence numbers (m bits) on a link with 10% data loss and 50% ACK loss. When the "
            "window breaks the textbook limit, a retransmitted *old* packet carries the same sequence "
            "number as a *new* one the receiver is waiting for; the receiver accepts the wrong data and "
            "only the end-to-end SHA-256 check catches it ('corrupted'). 'stalled' means the sender and "
            "receiver lost agreement on the window entirely and the transfer was aborted.",
            "",
            _md_table(rows, ["protocol", "seq_bits", "seq_space", "window", "rule", "correct", "corrupted",
                             "stalled"]),
            "",
        ]

    # ------------------------------------------------------------- exp 6

    def exp6_seqtime(self):
        self.say("\n[exp6] sequence/time diagrams")
        from .plots import seq_time_plot
        data = os.urandom(100 * MSS)
        traces = {}
        for proto, label in (("gbn", "Go-Back-N N=8"), ("sr", "Selective Repeat N=8")):
            link = LinkConfig(loss=0.05, delay_ms=10, rate_kbps=4000, seed=11)
            s, _ = run_local_transfer(data, SenderConfig(protocol=proto, window=8, min_rto=BENCH_MIN_RTO), link,
                                      LinkConfig(delay_ms=10, seed=12))
            traces[label] = s.trace
            self.say(f"   {label:<22} {s.data_s:.2f} s, {s.stats['retransmissions']} retransmissions")
        seq_time_plot(self.p("exp6_seq_time.png"), traces,
                      "Same loss pattern (5%): GBN resends whole windows, SR only the holes")
        self.md += [
            "## Experiment 6 - Sequence / time diagram",
            "Blue dots: first transmissions. Red crosses: retransmissions. Green: cumulative ACK. "
            "Vertical red lines: timeouts. Both runs use the same random seed for the link.",
            "",
            "![seq-time](exp6_seq_time.png)",
            "",
        ]

    # ------------------------------------------------------------- run all

    ALL = ("exp1", "exp2", "exp3", "exp4", "exp5", "exp6")

    def run(self, only=None):
        t0 = time.time()
        steps = {"exp1": self.exp1_loss, "exp2": self.exp2_window, "exp3": self.exp3_congestion,
                 "exp4": self.exp4_checksum, "exp5": self.exp5_seqspace, "exp6": self.exp6_seqtime}
        sec_dir = self.p("_sections")
        os.makedirs(sec_dir, exist_ok=True)
        for name in only or self.ALL:
            t = time.time()
            self.md = []
            steps[name]()
            with open(os.path.join(sec_dir, name + ".md"), "w") as f:
                f.write("\n".join(self.md))
            self.say(f"   ({name} took {time.time() - t:.0f} s)")
        # Re-assemble the report from every section on disk, so `--only exp2`
        # refreshes one experiment without losing the others.
        sections = []
        for name in self.ALL:
            path = os.path.join(sec_dir, name + ".md")
            if os.path.exists(path):
                with open(path) as f:
                    sections.append(f.read())
        header = [
            "# RUDP benchmark report",
            "",
            f"Last updated {time.strftime('%Y-%m-%d %H:%M')} by `python -m rudp bench"
            f"{' --quick' if self.quick else ''}`. All transfers are real UDP "
            "transfers over 127.0.0.1 through the link emulator; every file was checked end-to-end "
            "with SHA-256 (column `verified`). The RTO floor is 100 ms (Linux uses 200 ms for real "
            "WAN RTTs; the emulated RTT here is only 20-40 ms).",
            "",
        ]
        with open(self.p("REPORT.md"), "w") as f:
            f.write("\n".join(header + sections))
        self.say(f"\nDone in {time.time() - t0:.0f} s. Report: {self.p('REPORT.md')}")
