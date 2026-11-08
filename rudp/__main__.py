"""Command line interface.

    python -m rudp recv  --port 9000 --out received
    python -m rudp send  photo.jpg --to 192.168.1.20:9000 --proto sr --window 32 --cc reno
    python -m rudp demo  --proto gbn --loss 0.2
    python -m rudp bench [--quick]
    python -m rudp plot  trace.json
    python -m rudp crc   1101011011 10011
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import time

from .channel import ImpairedSocket, LinkConfig, make_udp_socket
from .log import EventLog, link_logger


def _add_link_args(p: argparse.ArgumentParser, direction: str) -> None:
    g = p.add_argument_group(f"link emulation ({direction})")
    g.add_argument("--loss", type=float, default=0.0, help="random loss probability, e.g. 0.05")
    g.add_argument("--corrupt", type=float, default=0.0, help="bit-error probability per frame")
    g.add_argument("--dup", type=float, default=0.0, help="duplication probability")
    g.add_argument("--delay", type=float, default=0.0, help="one-way propagation delay (ms)")
    g.add_argument("--jitter", type=float, default=0.0, help="random extra delay 0..J ms (reordering)")
    g.add_argument("--rate", type=float, default=0.0, help="bottleneck bandwidth in kbit/s (0 = unlimited)")
    g.add_argument("--queue", type=int, default=100, help="bottleneck queue size (packets)")
    g.add_argument("--burst-p", type=float, default=0.0, help="Gilbert-Elliott P(good->bad)")
    g.add_argument("--burst-r", type=float, default=0.5, help="Gilbert-Elliott P(bad->good)")
    g.add_argument("--seed", type=int, default=None, help="random seed for repeatable runs")


def _link(a) -> LinkConfig:
    return LinkConfig(loss=a.loss, corrupt=a.corrupt, duplicate=a.dup, delay_ms=a.delay,
                      jitter_ms=a.jitter, rate_kbps=a.rate, queue=a.queue, burst_p=a.burst_p,
                      burst_r=a.burst_r, seed=a.seed)


def _add_proto_args(p: argparse.ArgumentParser) -> None:
    g = p.add_argument_group("protocol")
    g.add_argument("--proto", choices=["sw", "gbn", "sr"], default="sr",
                   help="sw = Stop-and-Wait, gbn = Go-Back-N, sr = Selective Repeat (default)")
    g.add_argument("--window", "-N", type=int, default=16, help="window size N in packets")
    g.add_argument("--cc", choices=["none", "tahoe", "reno"], default="none", help="congestion control")
    g.add_argument("--mss", type=int, default=1024, help="payload bytes per packet")
    g.add_argument("--seq-bits", type=int, default=None, help="sequence number bits m (default 32, SW: 1)")
    g.add_argument("--checksum", choices=["crc32", "inet16"], default="crc32")
    g.add_argument("--min-rto", type=float, default=0.2, help="minimum retransmission timeout (s)")
    g.add_argument("--unsafe", action="store_true", help="allow windows that break the seq-space rule")


def _sender_cfg(a):
    from .sender import SenderConfig
    return SenderConfig(protocol=a.proto, window=a.window, cc=a.cc, mss=a.mss, seq_bits=a.seq_bits,
                        checksum=a.checksum, min_rto=a.min_rto, unsafe=a.unsafe)


def _parse_dest(s: str, default_port: int = 9000):
    host, _, port = s.rpartition(":") if ":" in s else (s, "", str(default_port))
    return socket.gethostbyname(host), int(port)


def _local_ips():
    ips = set()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))  # no packet is sent; just picks the outgoing interface
        ips.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    return sorted(ips) or ["127.0.0.1"]


def _progress_bar(sender) -> None:
    done, total = sender.acked_count(), max(1, sender.total)
    frac = done / total
    elapsed = time.monotonic() - sender.t_data
    rate = done * sender.cfg.mss / max(elapsed, 1e-9) / 1024
    bar = "#" * int(frac * 30)
    cw = sender.cc.cwnd
    cw = "-" if cw == float("inf") else f"{cw:.1f}"
    sys.stderr.write(f"\r  [{bar:<30}] {frac:6.1%}  {rate:8.1f} KB/s  retx {sender.stats.retransmissions:5}"
                     f"  timeouts {sender.stats.timeouts:4}  cwnd {cw:>5}  rto {sender.rtt.rto * 1000:5.0f} ms ")
    sys.stderr.flush()


# --------------------------------------------------------------------- commands

def cmd_recv(a) -> int:
    from .receiver import Receiver, ReceiverConfig
    log = EventLog(a.verbose, "RECEIVER")
    sock = ImpairedSocket(make_udp_socket(a.host, a.port), _link(a),
                          on_event=link_logger(EventLog(a.verbose, "LINK<-")))
    rx = Receiver(sock, ReceiverConfig(out_dir=a.out, linger=a.linger, idle_timeout=a.idle), log)
    print(f"RUDP receiver listening on UDP {a.host}:{a.port}  ->  saving into '{a.out}/'")
    if a.host in ("0.0.0.0", ""):
        print("  this machine's address(es): " + ", ".join(_local_ips()))
        print(f"  on the other laptop run:  python -m rudp send FILE --to {_local_ips()[0]}:{a.port}")
    code = 0
    try:
        while True:
            res = rx.serve_one()
            if res is None:
                continue
            print("\n" + ("=" * 64) + "\n" + res.summary() + "\n" + "=" * 64)
            if a.json:
                with open(a.json, "w") as f:
                    json.dump(res.to_dict(), f, indent=2)
            code = 0 if res.ok else 1
            if not a.keep:
                break
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        sock.close()
    return code


def cmd_send(a) -> int:
    from .sender import TransferError, make_sender
    if not os.path.isfile(a.file):
        print(f"error: no such file: {a.file}", file=sys.stderr)
        return 2
    dest = _parse_dest(a.to)
    log = EventLog(a.verbose, "SENDER")
    sock = ImpairedSocket(make_udp_socket(a.bind, 0), _link(a),
                          on_event=link_logger(EventLog(a.verbose, "LINK->")))
    try:
        sender = make_sender(sock, dest, _sender_cfg(a), log=log,
                             progress=None if a.verbose else _progress_bar)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    size = os.path.getsize(a.file)
    print(f"Sending '{a.file}' ({size:,} bytes) to {dest[0]}:{dest[1]} using {sender.protocol.upper()}"
          f" N={sender.cfg.window} cc={sender.cfg.cc}")
    try:
        res = sender.send_file(a.file)
    except TransferError as e:
        print(f"\nerror: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\naborted")
        return 130
    finally:
        sock.close()
    if not a.verbose:
        _progress_bar(sender)
        sys.stderr.write("\n")
    print("\n" + ("=" * 64) + "\n" + res.summary())
    ch = sock.stats
    if ch.offered and (a.loss or a.corrupt or a.dup or a.rate or a.burst_p):
        print(f"  emulated link   : {ch.offered} offered, {ch.dropped_random} lost, {ch.dropped_burst} burst-lost,"
              f" {ch.dropped_queue} queue drops, {ch.corrupted} corrupted, {ch.duplicated} duplicated")
    print("=" * 64)
    if a.json:
        with open(a.json, "w") as f:
            json.dump(res.to_dict(with_trace=True), f, indent=2)
        print(f"trace written to {a.json}  (plot it: python -m rudp plot {a.json})")
    return 0 if res.verified else 1


def cmd_demo(a) -> int:
    from .local import run_local_transfer
    from .sender import TransferError
    cfg = _sender_cfg(a)
    data_link = _link(a)
    ack_link = LinkConfig(loss=a.ack_loss, delay_ms=a.delay, jitter_ms=a.jitter,
                          seed=None if a.seed is None else a.seed + 1)
    payload = os.urandom(a.packets * a.mss - a.mss // 3)  # last packet deliberately shorter
    print(f"DEMO: {a.packets} packets, {cfg.protocol.upper()} N={cfg.window} cc={cfg.cc}  |  data link: "
          f"loss={a.loss:.0%} corrupt={a.corrupt:.0%} dup={a.dup:.0%} delay={a.delay}ms jitter={a.jitter}ms"
          f"  |  ACK link: loss={a.ack_loss:.0%}\n")
    try:
        s, r = run_local_transfer(payload, cfg, data_link, ack_link, verbose=True)
    except (TransferError, ValueError) as e:
        print(f"\nerror: {e}")
        return 1
    print("\n" + "=" * 64 + "\n" + s.summary())
    if r is not None:
        rs = r.stats
        print(f"  receiver        : {rs['corrupt_dropped']} corrupt frames dropped, {rs['duplicates']} duplicates,"
              f" {rs['out_of_order_buffered']} buffered / {rs['out_of_order_discarded']} discarded out-of-order")
    print("=" * 64)
    return 0 if s.verified else 1


def cmd_bench(a) -> int:
    from .experiments import Bench
    only = a.only.split(",") if a.only else None
    Bench(a.out, quick=a.quick).run(only)
    return 0


def cmd_plot(a) -> int:
    from .plots import cwnd_plot, rtt_plot, seq_time_plot
    with open(a.trace) as f:
        d = json.load(f)
    tr = d["trace"]
    base = os.path.splitext(a.trace)[0]
    label = f"{d['protocol'].upper()} {d['cc']}"
    seq_time_plot(base + "_seq.png", {label: tr})
    rtt_plot(base + "_rtt.png", tr)
    if d["cc"] != "none":
        cwnd_plot(base + "_cwnd.png", {label: tr})
    print("wrote " + ", ".join(p for p in (base + "_seq.png", base + "_rtt.png", base + "_cwnd.png")
                               if os.path.exists(p)))
    return 0


def cmd_crc(a) -> int:
    from .checksum import crc_divide_steps
    if set(a.message + a.generator) - {"0", "1"}:
        print("message and generator must be bit strings, e.g. 1101011011 10011")
        return 2
    rem, lines = crc_divide_steps(a.message, a.generator)
    print(f"CRC with generator G = {a.generator}  (degree {len(a.generator) - 1})\n")
    print("\n".join(lines))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m rudp", description="Reliable file transfer over UDP "
                                 "(Stop-and-Wait / Go-Back-N / Selective Repeat + Tahoe/Reno)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("recv", help="run a receiver (server)")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=9000)
    p.add_argument("--out", default="received", help="directory for received files")
    p.add_argument("--keep", action="store_true", help="keep serving after the first file")
    p.add_argument("--linger", type=float, default=3.0, help="TIME_WAIT seconds")
    p.add_argument("--idle", type=float, default=30.0, help="abort a silent session after N seconds")
    p.add_argument("--json", help="write the result summary as JSON")
    p.add_argument("-v", "--verbose", action="store_true", help="print every packet event")
    _add_link_args(p, "applied to ACKs sent by the receiver")
    p.set_defaults(fn=cmd_recv)

    p = sub.add_parser("send", help="send a file to a receiver")
    p.add_argument("file")
    p.add_argument("--to", required=True, help="receiver HOST[:PORT] (default port 9000)")
    p.add_argument("--bind", default="0.0.0.0")
    p.add_argument("--json", help="write result + full trace (for `plot`) as JSON")
    p.add_argument("-v", "--verbose", action="store_true", help="print every packet event")
    _add_proto_args(p)
    _add_link_args(p, "applied to data sent by the sender")
    p.set_defaults(fn=cmd_send)

    p = sub.add_parser("demo", help="sender + receiver in one terminal with a full event log")
    p.add_argument("--packets", type=int, default=12)
    p.add_argument("--ack-loss", type=float, default=0.0)
    _add_proto_args(p)
    _add_link_args(p, "data direction; delay/jitter also used for ACKs")
    p.set_defaults(fn=cmd_demo, proto="gbn", window=4, loss=0.15, delay=20.0, seed=7, min_rto=0.2)

    p = sub.add_parser("bench", help="run all experiments, write CSV + PNG + REPORT.md")
    p.add_argument("--out", default="results")
    p.add_argument("--quick", action="store_true", help="smaller sweeps (about 1-2 minutes)")
    p.add_argument("--only", help="comma separated subset, e.g. exp1,exp3")
    p.set_defaults(fn=cmd_bench)

    p = sub.add_parser("plot", help="plot a trace written by `send --json`")
    p.add_argument("trace")
    p.set_defaults(fn=cmd_plot)

    p = sub.add_parser("crc", help="CRC long-division calculator (shows the working)")
    p.add_argument("message")
    p.add_argument("generator")
    p.set_defaults(fn=cmd_crc)

    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
