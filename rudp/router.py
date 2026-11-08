"""A UDP "router" (middlebox) with an impaired link: ``python -m rudp router``.

Instead of each end impairing its own outgoing packets, put the bad network
*between* them, the way a real congested router or noisy wireless hop would
be:

    sender  --->  router :9000  ===[ loss, delay, queue, bit errors ]===>  receiver :9001
    sender  <---  router        <==[ ACK-direction impairments ]=========  receiver

The sender is pointed at the router (``send FILE --to ROUTER_IP:9000``) and
the router forwards to the real receiver (``--to RECEIVER_IP:9001``). The
router knows nothing about RUDP: it just relays datagrams, so the protocol
has to survive whatever the router does to them. This works across three
laptops, or in three terminals on one.
"""

from __future__ import annotations

import select
import socket
import time

from .channel import ImpairedSocket, LinkConfig, make_udp_socket
from .log import EventLog, link_logger


def run_router(listen: tuple, target: tuple, data_link: LinkConfig, ack_link: LinkConfig,
               verbose: bool = False, report_every: float = 5.0, stop_after: float | None = None) -> dict:
    """Relay datagrams until Ctrl+C (or ``stop_after`` seconds). Returns link stats."""
    front = make_udp_socket(*listen)  # clients (senders) talk to this one
    back = make_udp_socket("0.0.0.0", 0)  # this one talks to the receiver
    front.setblocking(False)
    back.setblocking(False)
    to_receiver = ImpairedSocket(back, data_link,
                                 on_event=link_logger(EventLog(verbose, "ROUTER->")))
    to_sender = ImpairedSocket(front, ack_link,
                               on_event=link_logger(EventLog(verbose, "ROUTER<-")))
    client = None
    fwd = rev = 0
    last_report = time.monotonic()
    last_counts = (0, 0)
    deadline = None if stop_after is None else time.monotonic() + stop_after
    try:
        while deadline is None or time.monotonic() < deadline:
            ready, _, _ = select.select([front, back], [], [], 0.5)
            for s in ready:
                while True:
                    try:
                        data, addr = s.recvfrom(65535)
                    except (BlockingIOError, InterruptedError):
                        break
                    except OSError:
                        break
                    if s is front:
                        if client != addr:
                            client = addr
                            print(f"  sender {addr[0]}:{addr[1]} -> forwarding to {target[0]}:{target[1]}")
                        fwd += 1
                        to_receiver.sendto(data, target)
                    elif addr == target and client is not None:
                        rev += 1
                        to_sender.sendto(data, client)
            now = time.monotonic()
            if now - last_report >= report_every and (fwd, rev) != last_counts:
                last_report, last_counts = now, (fwd, rev)
                d, a = to_receiver.stats, to_sender.stats
                print(f"  [{time.strftime('%H:%M:%S')}] data {fwd} in -> {d.delivered} out"
                      f" ({d.dropped_random + d.dropped_burst} lost, {d.dropped_queue} queue drops,"
                      f" {d.corrupted} corrupted) | ACKs {rev} in -> {a.delivered} out"
                      f" ({a.dropped_random + a.dropped_burst} lost)")
    except KeyboardInterrupt:
        print("\nrouter stopped")
    finally:
        to_receiver.close(flush=False)
        to_sender.close(flush=False)
    return {"forwarded": fwd, "returned": rev, "data_link": to_receiver.stats.to_dict(),
            "ack_link": to_sender.stats.to_dict()}


def resolve(hostport: str, default_port: int) -> tuple:
    host, _, port = hostport.rpartition(":") if ":" in hostport else (hostport, "", str(default_port))
    return socket.gethostbyname(host or "127.0.0.1"), int(port)
