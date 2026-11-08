"""Live visualizer: ``python -m rudp viz``.

Runs a *real* RUDP transfer (real UDP sockets on 127.0.0.1, real sender and
receiver code) in slow motion - the emulated link gets a long propagation
delay - and streams every protocol event to a web page that animates it:
packets flying, losses, corruption, the sender and receiver windows sliding,
retransmission timers running out, and cwnd.

Only the standard library is used: ``http.server`` for the page and
Server-Sent Events (SSE) for the live event stream.
"""

from __future__ import annotations

import json
import os
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional
from urllib.parse import parse_qs, urlparse

from .channel import LinkConfig
from .local import run_local_transfer
from .sender import SenderConfig, TransferError

PAGE = os.path.join(os.path.dirname(__file__), "web", "viz.html")
MAX_PACKETS = 80


class Run:
    def __init__(self, run_id: int, params: dict):
        self.id = run_id
        self.params = params
        self.events: list[dict] = []
        self.cv = threading.Condition()
        self.done = False
        self.sender = None
        self.t0 = time.monotonic()

    def push(self, ev: dict) -> None:
        with self.cv:
            ev["t"] = round(time.monotonic() - self.t0, 4)
            self.events.append(ev)
            self.cv.notify_all()

    def finish(self) -> None:
        with self.cv:
            self.done = True
            self.cv.notify_all()

    def abort(self) -> None:
        if self.sender is not None:
            self.sender.abort()


def _num(d: dict, key: str, default, lo, hi, cast=float):
    try:
        v = cast(d.get(key, default))
    except (TypeError, ValueError):
        v = default
    return max(lo, min(hi, v))


def build_config(p: dict) -> dict:
    """Validate the form values coming from the page."""
    proto = p.get("protocol") if p.get("protocol") in ("sw", "gbn", "sr") else "gbn"
    cc = p.get("cc") if p.get("cc") in ("none", "tahoe", "reno") else "none"
    seq_bits = p.get("seq_bits")
    seq_bits = None if seq_bits in (None, "", "auto") else _num(p, "seq_bits", 32, 1, 32, int)
    seed = p.get("seed")
    seed = None if seed in (None, "") else _num(p, "seed", 0, 0, 10**9, int)
    return {
        "protocol": proto, "cc": cc, "seq_bits": seq_bits, "seed": seed,
        "window": 1 if proto == "sw" else _num(p, "window", 4, 1, 64, int),
        "packets": _num(p, "packets", 16, 1, MAX_PACKETS, int),
        "loss": _num(p, "loss", 0.15, 0, 0.9),
        "ack_loss": _num(p, "ack_loss", 0.0, 0, 0.9),
        "corrupt": _num(p, "corrupt", 0.0, 0, 0.9),
        "dup": _num(p, "dup", 0.0, 0, 0.9),
        "delay_ms": _num(p, "delay_ms", 700, 20, 5000),
        "jitter_ms": _num(p, "jitter_ms", 0, 0, 3000),
        "unsafe": bool(p.get("unsafe")),
    }


def execute(run: Run) -> None:
    c = run.params
    rtt = 2 * c["delay_ms"] / 1000 + c["jitter_ms"] / 1000
    # Timers must be scaled to the slow-motion link or every packet would time out.
    min_rto = max(0.2, 1.6 * rtt)
    cfg = SenderConfig(protocol=c["protocol"], window=c["window"], cc=c["cc"], mss=1024,
                       seq_bits=c["seq_bits"], unsafe=c["unsafe"], initial_rto=2.5 * rtt + 0.2,
                       min_rto=min_rto, max_rto=max(4 * min_rto, 4.0), max_retries=10)
    try:
        cfg_n = cfg.normalised()
    except ValueError as e:
        run.push({"type": "error", "src": "-", "msg": str(e)})
        run.finish()
        return
    seed = c["seed"]
    data_link = LinkConfig(loss=c["loss"], corrupt=c["corrupt"], duplicate=c["dup"],
                           delay_ms=c["delay_ms"], jitter_ms=c["jitter_ms"], seed=seed)
    ack_link = LinkConfig(loss=c["ack_loss"], delay_ms=c["delay_ms"], jitter_ms=c["jitter_ms"],
                          seed=None if seed is None else seed + 1)
    size = c["packets"] * 1024 - 300
    run.push({"type": "config", "src": "-", "packets": c["packets"], "M": 1 << cfg_n.seq_bits,
              "seq_bits": cfg_n.seq_bits, "protocol": cfg_n.protocol, "window": cfg_n.window,
              "cc": cfg_n.cc, "delay_ms": c["delay_ms"], "jitter_ms": c["jitter_ms"],
              "loss": c["loss"], "ack_loss": c["ack_loss"], "corrupt": c["corrupt"], "dup": c["dup"],
              "min_rto": min_rto, "bytes": size})

    def grab(sender):
        run.sender = sender

    try:
        s, r = run_local_transfer(os.urandom(size), cfg_n, data_link, ack_link, name="demo.bin",
                                  on_event=run.push, on_sender=grab)
        run.push({"type": "end", "src": "-", "verified": s.verified,
                  "receiver_ok": None if r is None else r.ok, "summary": s.to_dict()})
    except TransferError as e:
        run.push({"type": "error", "src": "-", "msg": str(e)})
    except Exception as e:  # pragma: no cover - shown on the page instead of killing the server
        run.push({"type": "error", "src": "-", "msg": f"{type(e).__name__}: {e}"})
    finally:
        run.finish()


class VizServer:
    def __init__(self):
        self.lock = threading.Lock()
        self.current: Optional[Run] = None
        self.counter = 0

    def start_run(self, params: dict) -> Run:
        with self.lock:
            if self.current is not None and not self.current.done:
                self.current.abort()
            self.counter += 1
            run = Run(self.counter, build_config(params))
            self.current = run
        threading.Thread(target=execute, args=(run,), name=f"viz-run-{run.id}", daemon=True).start()
        return run


def make_handler(app: VizServer):
    class Handler(BaseHTTPRequestHandler):
        server_version = "rudp-viz"

        def log_message(self, fmt, *args):  # keep the terminal quiet
            pass

        def _json(self, code: int, obj) -> None:
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            url = urlparse(self.path)
            if url.path in ("/", "/index.html"):
                with open(PAGE, "rb") as f:
                    body = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
            elif url.path == "/events":
                self._stream(parse_qs(url.query))
            else:
                self.send_error(404)

        def do_POST(self):
            url = urlparse(self.path)
            length = min(int(self.headers.get("Content-Length") or 0), 10_000)
            try:
                params = json.loads(self.rfile.read(length) or b"{}")
            except ValueError:
                params = {}
            if url.path == "/run":
                run = app.start_run(params if isinstance(params, dict) else {})
                self._json(200, {"run": run.id, "config": run.params})
            elif url.path == "/abort":
                if app.current is not None:
                    app.current.abort()
                self._json(200, {"ok": True})
            else:
                self.send_error(404)

        def _stream(self, q: dict) -> None:
            run = app.current
            try:
                want = int(q.get("run", ["0"])[0])
            except ValueError:
                want = 0
            if run is None or run.id != want:
                self.send_error(404, "no such run")
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            sent = 0
            try:
                while True:
                    with run.cv:
                        while sent >= len(run.events) and not run.done:
                            if not run.cv.wait(timeout=10):
                                break
                        batch = run.events[sent:]
                        finished = run.done and sent + len(batch) >= len(run.events)
                    if batch:
                        payload = "".join(f"data: {json.dumps(e)}\n\n" for e in batch)
                        self.wfile.write(payload.encode())
                        sent += len(batch)
                    else:
                        self.wfile.write(b": keep-alive\n\n")
                    self.wfile.flush()
                    if finished:
                        self.wfile.write(b"event: close\ndata: {}\n\n")
                        self.wfile.flush()
                        return
                    if app.current is not run:  # superseded by a newer run
                        return
            except (BrokenPipeError, ConnectionResetError):
                return

    return Handler


def serve(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True) -> None:
    app = VizServer()
    httpd = ThreadingHTTPServer((host, port), make_handler(app))
    httpd.daemon_threads = True
    url = f"http://{'localhost' if host in ('127.0.0.1', '0.0.0.0') else host}:{httpd.server_port}/"
    print(f"RUDP live visualizer running at {url}   (Ctrl+C to stop)")
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        httpd.server_close()
