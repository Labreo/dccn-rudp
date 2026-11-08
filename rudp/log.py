"""Coloured, time-stamped event log used by ``--verbose`` and ``demo``."""

from __future__ import annotations

import os
import sys
import threading
import time

_COLORS = {
    "SEND": "36",  # cyan
    "RETX": "33;1",  # bold yellow
    "ACK": "32",  # green
    "DUPACK": "33",  # yellow
    "TIMEOUT": "31;1",  # bold red
    "FASTRETX": "35;1",  # bold magenta
    "DROP": "31",  # red
    "QDROP": "31",
    "BURST": "31",
    "CORRUPT": "35",  # magenta
    "BADCRC": "35",
    "DUP": "34",  # blue
    "DELIVER": "32",
    "BUFFER": "34",
    "DISCARD": "90",  # grey
    "SYN": "1",
    "SYNACK": "1",
    "FIN": "1",
    "FINACK": "1",
    "CWND": "90",
    "INFO": "0",
    "OK": "32;1",
    "FAIL": "31;1",
}

_print_lock = threading.Lock()


def _supports_color(stream) -> bool:
    return hasattr(stream, "isatty") and stream.isatty() and os.environ.get("NO_COLOR") is None


class EventLog:
    def __init__(self, enabled: bool = False, side: str = "", t0: float | None = None,
                 stream=None, color: bool | None = None):
        self.enabled = enabled
        self.side = side
        self.t0 = t0 if t0 is not None else time.monotonic()
        self.stream = stream or sys.stdout
        self.color = _supports_color(self.stream) if color is None else color

    def __call__(self, kind: str, msg: str = "") -> None:
        if not self.enabled:
            return
        t = time.monotonic() - self.t0
        side = f"{self.side:<7}" if self.side else ""
        line = f"{t:8.3f}s  {side} {kind:<8} {msg}"
        if self.color:
            code = _COLORS.get(kind, "0")
            line = f"\x1b[{code}m{line}\x1b[0m"
        with _print_lock:
            print(line, file=self.stream, flush=True)


def link_logger(log: EventLog):
    """Adapter so ImpairedSocket can report what the 'wire' did to a frame."""
    from .packet import peek

    def hook(kind: str, raw: bytes) -> None:
        verb = {"DROP": "lost on wire:", "QDROP": "queue overflow, dropped:",
                "BURST": "burst loss:", "CORRUPT": "bit errors in:",
                "DUP": "duplicated:"}.get(kind, kind)
        log(kind, f"~~ link ~~ {verb} {peek(raw)}")

    return hook
