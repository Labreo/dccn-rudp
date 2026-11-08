import json
import os
import threading
import time
import urllib.request

import pytest

from rudp.channel import ImpairedSocket, LinkConfig, make_udp_socket
from rudp.local import run_local_transfer
from rudp.receiver import Receiver, ReceiverConfig
from rudp.router import run_router
from rudp.sender import SenderConfig, TransferError, make_sender
from rudp.viz import Run, build_config, execute

DATA = os.urandom(20 * 1024)


def test_events_cover_whole_conversation():
    events = []
    s, r = run_local_transfer(DATA, SenderConfig(protocol="sr", window=4, cc="reno"),
                              LinkConfig(loss=0.15, corrupt=0.05, delay_ms=3, seed=8),
                              LinkConfig(loss=0.1, delay_ms=3, seed=9), on_event=events.append)
    kinds = {(e["src"], e["type"]) for e in events}
    for need in [("S", "syn"), ("R", "rx_syn"), ("S", "established"), ("S", "send"), ("R", "rx"),
                 ("R", "rx_ack"), ("S", "ack"), ("S", "timers"), ("L>", "link"), ("S", "fin"),
                 ("R", "rx_fin"), ("S", "finack"), ("S", "cwnd")]:
        assert need in kinds, need
    sends = [e for e in events if e["type"] == "send"]
    assert len(sends) == s.stats["data_packets_sent"]
    assert not any(e["type"] == "wrongdata" for e in events)  # safe window: never stale data
    json.dumps(events)  # everything must be serialisable for the web page


def test_wrongdata_event_marks_stale_delivery():
    events = []
    cfg = SenderConfig(protocol="sr", window=6, seq_bits=3, unsafe=True, min_rto=0.05, max_retries=10)
    for seed in range(6):
        try:
            run_local_transfer(DATA * 2, cfg, LinkConfig(loss=0.1, delay_ms=3, seed=seed),
                               LinkConfig(loss=0.4, delay_ms=3, seed=seed + 50), on_event=events.append)
        except TransferError:
            pass
        if any(e["type"] == "wrongdata" for e in events):
            break
    assert any(e["type"] == "wrongdata" for e in events)


def test_abort_stops_sender():
    box = {}

    def grab(sender):
        box["s"] = sender
        threading.Timer(0.3, sender.abort).start()

    with pytest.raises(TransferError, match="aborted"):
        run_local_transfer(os.urandom(400 * 1024), SenderConfig(protocol="sw"),
                           LinkConfig(delay_ms=20), LinkConfig(delay_ms=20), on_sender=grab)


def test_build_config_clamps_bad_input():
    c = build_config({"protocol": "evil", "window": 9999, "packets": -5, "loss": 5, "seq_bits": "x",
                      "delay_ms": "abc"})
    assert c["protocol"] == "gbn" and c["window"] == 64 and c["packets"] == 1
    assert c["loss"] == 0.9 and c["seq_bits"] == 32 and c["delay_ms"] == 700
    assert build_config({"protocol": "sw", "window": 8})["window"] == 1


def test_viz_execute_runs_a_fast_transfer():
    run = Run(1, build_config({"protocol": "gbn", "window": 3, "packets": 6, "loss": 0.2, "delay_ms": 20,
                               "seed": 3}))
    execute(run)
    assert run.done
    types = [e["type"] for e in run.events]
    assert types[0] == "config" and types[-1] == "end"
    assert run.events[-1]["verified"] is True


def test_viz_http_server_serves_page_and_stream():
    from http.server import ThreadingHTTPServer
    from rudp.viz import VizServer, make_handler
    app = VizServer()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_port}"
    try:
        page = urllib.request.urlopen(base + "/").read().decode()
        assert "RUDP Live Visualizer" in page
        req = urllib.request.Request(base + "/run", method="POST", headers={"Content-Type": "application/json"},
                                     data=json.dumps({"protocol": "sr", "packets": 4, "loss": 0,
                                                      "delay_ms": 20}).encode())
        run_id = json.loads(urllib.request.urlopen(req).read())["run"]
        body = urllib.request.urlopen(f"{base}/events?run={run_id}", timeout=30).read().decode()
        events = [json.loads(line[6:]) for line in body.splitlines() if line.startswith("data: {") and line != "data: {}"]
        assert events[0]["type"] == "config" and events[-1]["type"] == "end"
        assert "event: close" in body
    finally:
        httpd.shutdown()


def test_router_relays_through_impaired_link(tmp_path):
    rsock = ImpairedSocket(make_udp_socket("127.0.0.1", 0))
    target = rsock.getsockname()
    probe = make_udp_socket("127.0.0.1", 0)
    router_port = probe.getsockname()[1]
    probe.close()
    th = threading.Thread(target=run_router, kwargs=dict(
        listen=("127.0.0.1", router_port), target=target,
        data_link=LinkConfig(loss=0.1, corrupt=0.02, delay_ms=3, seed=1),
        ack_link=LinkConfig(loss=0.05, delay_ms=3, seed=2), report_every=999, stop_after=20), daemon=True)
    th.start()
    time.sleep(0.2)
    rx = Receiver(rsock, ReceiverConfig(out_dir=str(tmp_path), linger=0.5))
    box = {}
    rt = threading.Thread(target=lambda: box.setdefault("r", rx.serve_one(timeout=20)), daemon=True)
    rt.start()
    ssock = ImpairedSocket(make_udp_socket("127.0.0.1", 0))
    sender = make_sender(ssock, ("127.0.0.1", router_port), SenderConfig(protocol="gbn", window=8, min_rto=0.05))
    res = sender.send_bytes(DATA, "via-router.bin")
    rt.join(5)
    ssock.close(); rsock.close()
    assert res.verified and box["r"].ok
    assert res.stats["retransmissions"] > 0  # the router really dropped/corrupted packets
