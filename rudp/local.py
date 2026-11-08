"""Run a receiver and a sender in one process over 127.0.0.1.

Used by ``demo``, ``bench`` and the tests. Real UDP sockets are used, only
the two ends live in the same Python process (receiver in a thread).
"""

from __future__ import annotations

import tempfile
import threading
import time
from dataclasses import replace
from typing import Optional

from .channel import ImpairedSocket, LinkConfig, make_udp_socket
from .log import EventLog, link_logger
from .receiver import Receiver, ReceiverConfig
from .sender import SenderConfig, make_sender
from .stats import ReceiveResult, TransferResult


def run_local_transfer(data: bytes, cfg: SenderConfig, data_link: Optional[LinkConfig] = None,
                       ack_link: Optional[LinkConfig] = None, name: str = "file.bin",
                       out_dir: Optional[str] = None, verbose: bool = False,
                       linger: float = 10.0, color: Optional[bool] = None
                       ) -> tuple[TransferResult, Optional[ReceiveResult]]:
    data_link = data_link or LinkConfig()
    ack_link = ack_link or LinkConfig()
    if ack_link.seed is None and data_link.seed is not None:
        ack_link = replace(ack_link, seed=data_link.seed + 7919)

    t0 = time.monotonic()
    slog = EventLog(verbose, "SENDER", t0, color=color)
    rlog = EventLog(verbose, "RECEIVER", t0, color=color)
    tmp = None
    if out_dir is None:
        tmp = tempfile.TemporaryDirectory(prefix="rudp-")
        out_dir = tmp.name

    rsock = ImpairedSocket(make_udp_socket("127.0.0.1", 0), ack_link,
                           on_event=link_logger(EventLog(verbose, "LINK<-", t0, color=color)))
    ssock = ImpairedSocket(make_udp_socket("127.0.0.1", 0), data_link,
                           on_event=link_logger(EventLog(verbose, "LINK->", t0, color=color)))
    receiver = Receiver(rsock, ReceiverConfig(out_dir=out_dir, linger=linger, idle_timeout=15), rlog)
    box: dict = {}

    def serve():
        try:
            box["result"] = receiver.serve_one(timeout=30)
        except Exception as e:  # pragma: no cover - surfaced below
            box["error"] = e

    th = threading.Thread(target=serve, name="receiver", daemon=True)
    th.start()
    try:
        sender = make_sender(ssock, rsock.getsockname(), cfg, log=slog)
        sres = sender.send_bytes(data, name)
        sres.stats["link_data"] = ssock.stats.to_dict()
        sres.stats["link_ack"] = rsock.stats.to_dict()
    finally:
        receiver.stop()  # sender is done (FIN-ACK seen or gave up): end TIME_WAIT
        th.join(timeout=35)
        ssock.close()
        rsock.close()
        if tmp is not None:
            tmp.cleanup()
    if "error" in box:
        raise box["error"]
    return sres, box.get("result")
