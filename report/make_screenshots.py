"""Capture the report's execution screenshots.

    python report/make_screenshots.py            # everything
    python report/make_screenshots.py term       # terminal runs only
    python report/make_screenshots.py viz        # visualizer only

Terminal screenshots: each command is really run (inside `script` so it gets
a TTY and prints colours); its output is rendered as a terminal window.
Visualizer screenshots: the real `python -m rudp viz` server is started and
driven with Playwright. Output: report/screenshots/*.png
"""

from __future__ import annotations

import html
import os
import pathlib
import re
import signal
import subprocess
import sys
import tempfile
import time

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = pathlib.Path(__file__).resolve().parent / "screenshots"
PY = sys.executable

# ---------------------------------------------------------------- ANSI -> HTML

COLORS = {30: "#5c6370", 31: "#e06c75", 32: "#98c379", 33: "#e5c07b", 34: "#61afef",
          35: "#c678dd", 36: "#56b6c2", 37: "#dcdfe4", 90: "#7f848e", 91: "#ff7b86",
          92: "#b5e890", 93: "#f2d48f", 94: "#7cc2ff", 95: "#dd9cf0", 96: "#7fd4de", 97: "#ffffff"}
SGR = re.compile(r"\x1b\[([0-9;]*)m")
OTHER_ESC = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07]*\x07")


def clean_lines(raw: str) -> list[str]:
    raw = raw.replace("\r\n", "\n").replace("\x04", "").replace("\x08", "").replace("^D", "")
    raw = raw.replace(str(pathlib.Path.home()), "~")
    lines = []
    for line in raw.split("\n"):
        if "\r" in line:  # progress bars redraw with \r: keep the final state
            parts = [p for p in line.split("\r") if OTHER_ESC.sub("", SGR.sub("", p)).strip()]
            line = parts[-1] if parts else ""
        lines.append(OTHER_ESC.sub("", line).rstrip())
    while lines and not SGR.sub("", lines[-1]).strip():
        lines.pop()
    return lines


PROGRESS = re.compile(r"^\s*\[[# ]*\]\s+[0-9.]+%")


def squash_progress(lines: list[str], hide: str = "") -> list[str]:
    """Keep only the final progress-bar line, and hide temp paths."""
    plain = [SGR.sub("", l) for l in lines]
    bars = [i for i, l in enumerate(plain) if PROGRESS.match(l)]
    keep = set(range(len(lines))) - set(bars[:-1])
    out = [lines[i] for i in sorted(keep)]
    return [l.replace(hide + "/", "") for l in out] if hide else out


def ansi_to_html(line: str) -> str:
    out, pos, style = [], 0, {}

    def span(text):
        if not text:
            return
        css = ";".join(f"{k}:{v}" for k, v in style.items())
        out.append(f'<span style="{css}">{html.escape(text)}</span>' if css else html.escape(text))

    for m in SGR.finditer(line):
        span(line[pos:m.start()])
        pos = m.end()
        codes = [int(c) for c in m.group(1).split(";") if c] or [0]
        for c in codes:
            if c == 0:
                style = {}
            elif c == 1:
                style["font-weight"] = "700"
            elif c == 2:
                style["opacity"] = "0.6"
            elif c in COLORS:
                style["color"] = COLORS[c]
            elif c == 39:
                style.pop("color", None)
    span(line[pos:])
    return "".join(out)


TERM_PAGE = """<!doctype html><html><head><meta charset="utf-8"><style>
body{margin:0;padding:20px;background:#ffffff}
.win{width:%dpx;border-radius:10px;overflow:hidden;box-shadow:0 6px 24px rgba(0,0,0,.25);background:#1e2127}
.bar{height:30px;background:#2c313a;display:flex;align-items:center;padding:0 12px;gap:8px}
.dot{width:12px;height:12px;border-radius:50%%}
.title{flex:1;text-align:center;color:#9da5b4;font:13px -apple-system,Helvetica,Arial,sans-serif;margin-right:52px}
pre{margin:0;padding:14px 16px;color:#dcdfe4;font:13px/1.45 Menlo,Monaco,'Courier New',monospace;white-space:pre-wrap;word-break:break-all}
.prompt{color:#98c379}.cmd{color:#ffffff;font-weight:700}.gap{color:#7f848e;font-style:italic}
</style></head><body><div class="win" id="w"><div class="bar">
<div class="dot" style="background:#ff5f57"></div><div class="dot" style="background:#febc2e"></div>
<div class="dot" style="background:#28c840"></div><div class="title">%s</div></div><pre>%s</pre></div></body></html>"""


def term_block(cmd: str, lines: list[str], head: int | None = None, tail: int = 0) -> str:
    body = [f'<span class="prompt">$</span> <span class="cmd">{html.escape(cmd)}</span>']
    if head is not None and len(lines) > head + tail:
        skipped = len(lines) - head - tail
        shown = lines[:head]
        body += [ansi_to_html(l) for l in shown]
        body.append(f'<span class="gap">   ... {skipped} more lines ...</span>')
        body += [ansi_to_html(l) for l in lines[-tail:]] if tail else []
    else:
        body += [ansi_to_html(l) for l in lines]
    return "\n".join(body)


def run_tty(args: list[str], timeout: float = 300) -> str:
    """Run a command with a pseudo-terminal (so it prints colours) and return its output."""
    env = dict(os.environ, PYTHONUNBUFFERED="1", COLUMNS="110")
    res = subprocess.run(["script", "-q", "/dev/null", *args], cwd=ROOT, env=env,
                         capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
    return res.stdout


def run_cmp(a: pathlib.Path, b: pathlib.Path) -> list[str]:
    """Really run `cmp a b && echo identical` and return what it prints."""
    res = subprocess.run(f'cmp "{a}" "{b}" && echo identical', shell=True, capture_output=True, text=True)
    out = (res.stdout + res.stderr).replace(str(a.parent) + "/", "").replace(str(b.parent.parent) + "/", "")
    return out.strip().splitlines()


def shot_terminal(page, name: str, blocks: list[str], title: str, width: int = 1100) -> None:
    page.set_content(TERM_PAGE % (width, html.escape(title), "\n\n".join(blocks)))
    (OUT / f"{name}.txt").write_text(page.locator("pre").inner_text())
    page.locator("#w").screenshot(path=str(OUT / f"{name}.png"))
    print("wrote", OUT / f"{name}.png")


def terminal_shots(page) -> None:
    # 1. CRC long division
    cmd = ["python", "-m", "rudp", "crc", "1101011011", "10011"]
    out = clean_lines(run_tty([PY, *cmd[1:]]))
    shot_terminal(page, "t1_crc", [term_block(" ".join(cmd), out)], "CRC long division")

    # 2. Go-Back-N demo, 3. Selective Repeat demo (same seed)
    for name, proto in (("t2_demo_gbn", "gbn"), ("t3_demo_sr", "sr")):
        args = ["-m", "rudp", "demo", "--proto", proto]
        out = clean_lines(run_tty([PY, *args]))
        shot_terminal(page, name, [term_block("python " + " ".join(args), out, head=46, tail=14)],
                      f"python -m rudp demo --proto {proto}")

    # 4. Bit errors detected by CRC
    args = ["-m", "rudp", "demo", "--proto", "sr", "--packets", "10", "--corrupt", "0.3", "--loss", "0"]
    out = clean_lines(run_tty([PY, *args]))
    shot_terminal(page, "t4_demo_crc", [term_block("python " + " ".join(args), out, head=34, tail=12)],
                  "Bit errors caught by CRC-32")

    # 5. Unsafe window -> corrupted file detected by SHA-256
    args = ["-m", "rudp", "demo", "--proto", "sr", "--seq-bits", "3", "--window", "6", "--unsafe",
            "--packets", "40", "--loss", "0.1", "--ack-loss", "0.4"]
    out = clean_lines(run_tty([PY, *args]))
    shot_terminal(page, "t5_demo_unsafe", [term_block("python " + " ".join(args), out, head=8, tail=16)],
                  "Window larger than 2^(m-1): stale data detected")

    # 6. Two processes: receiver + sender with a real file
    with tempfile.TemporaryDirectory() as tmp:
        src = pathlib.Path(tmp) / "photo.jpg"
        src.write_bytes(os.urandom(512 * 1024))
        outdir = pathlib.Path(tmp) / "received"
        recv_log = pathlib.Path(tmp) / "recv.txt"
        rcv = subprocess.Popen(["script", "-q", str(recv_log), PY, "-m", "rudp", "recv", "--port", "9500",
                                "--out", str(outdir), "--linger", "1"], cwd=ROOT,
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
        time.sleep(1.0)
        send_args = ["-m", "rudp", "send", str(src), "--to", "127.0.0.1:9500", "--proto", "sr",
                     "--window", "32", "--cc", "reno", "--loss", "0.05", "--delay", "10"]
        sent = squash_progress(clean_lines(run_tty([PY, *send_args])), str(src.parent))
        rcv.wait(timeout=60)
        got = squash_progress(clean_lines(recv_log.read_text(errors="replace")), str(outdir.parent))
        cmp_line = run_cmp(src, outdir / "photo.jpg")
        shot_terminal(page, "t6_recv", [term_block("python -m rudp recv --port 9500 --out received", got)],
                      "Terminal 1: receiver")
        shot_terminal(page, "t7_send", [
            term_block("python -m rudp send photo.jpg --to 127.0.0.1:9500 --proto sr --window 32 "
                       "--cc reno --loss 0.05 --delay 10", sent),
            term_block("cmp photo.jpg received/photo.jpg && echo identical", cmp_line)],
            "Terminal 2: sender")

    # 7. Three processes through the router
    with tempfile.TemporaryDirectory() as tmp:
        src = pathlib.Path(tmp) / "notes.pdf"
        src.write_bytes(os.urandom(500 * 1024))
        outdir = pathlib.Path(tmp) / "received"
        rcv = subprocess.Popen([PY, "-m", "rudp", "recv", "--port", "9601", "--out", str(outdir),
                                "--linger", "1"], cwd=ROOT, stdin=subprocess.DEVNULL,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        router_args = ["-m", "rudp", "router", "--port", "9600", "--to", "127.0.0.1:9601",
                       "--loss", "0.08", "--corrupt", "0.02", "--rate", "6000", "--delay", "5"]
        rtr = subprocess.Popen([PY, *router_args], cwd=ROOT, stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                               env=dict(os.environ, PYTHONUNBUFFERED="1"))
        time.sleep(1.0)
        send_args = ["-m", "rudp", "send", str(src), "--to", "127.0.0.1:9600", "--proto", "sr",
                     "--window", "32", "--cc", "reno"]
        sent = squash_progress(clean_lines(run_tty([PY, *send_args])), str(src.parent))
        rcv.wait(timeout=60)
        time.sleep(5.5)  # let the router print one statistics line
        rtr.send_signal(signal.SIGINT)
        rout = clean_lines(rtr.communicate(timeout=10)[0])
        shot_terminal(page, "t8_router", [
            term_block("python " + " ".join(router_args), rout),
            term_block("python -m rudp send notes.pdf --to 127.0.0.1:9600 --proto sr --window 32 --cc reno", sent),
            term_block("cmp notes.pdf received/notes.pdf && echo identical",
                       run_cmp(src, outdir / "notes.pdf"))],
            "Sender → router (8% loss, 2% bit errors, 6 Mbit/s) → receiver")

    # 8. Test suite
    out = clean_lines(run_tty([PY, "-m", "pytest", "-v", "-p", "no:cacheprovider"], timeout=600))
    shot_terminal(page, "t9_pytest", [term_block("python -m pytest -v", out, head=60, tail=4)],
                  "Automated test suite", width=1200)


# ---------------------------------------------------------------- visualizer

def viz_shots(page) -> None:
    port = 8791
    srv = subprocess.Popen([PY, "-m", "rudp", "viz", "--no-browser", "--port", str(port)], cwd=ROOT,
                           stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(1.5)
        page.set_viewport_size({"width": 1440, "height": 1000})
        page.goto(f"http://127.0.0.1:{port}/")
        page.wait_for_selector(".chip")
        page.screenshot(path=str(OUT / "v0_start.png"), full_page=True)
        print("wrote", OUT / "v0_start.png")

        def run(chip: str, name: str, mid: float | None = None, limit: float = 240) -> None:
            page.locator(".chip", has_text=chip).first.click()
            t0 = time.time()
            page.wait_for_function("!document.getElementById('phase').textContent.includes('finished')",
                                   timeout=15000)
            if mid is not None:
                page.wait_for_timeout(mid * 1000)
                page.screenshot(path=str(OUT / f"{name}_running.png"), full_page=True)
                print("wrote", OUT / f"{name}_running.png")
            page.wait_for_function("document.getElementById('phase').textContent.includes('finished')",
                                   timeout=(limit - (time.time() - t0)) * 1000)
            page.wait_for_timeout(1500)
            page.screenshot(path=str(OUT / f"{name}.png"), full_page=True)
            print("wrote", OUT / f"{name}.png")

        run("Go-Back-N", "v1_gbn", mid=9)
        run("Selective Repeat", "v2_sr", mid=9)
        run("Bit errors", "v3_crc")
        run("TCP Reno", "v4_reno")
        run("Unsafe window", "v5_unsafe")
    finally:
        srv.terminate()
        srv.wait(timeout=10)


def main(which: list[str]) -> None:
    OUT.mkdir(exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(device_scale_factor=2)
        if not which or "term" in which:
            terminal_shots(page)
        if not which or "viz" in which:
            viz_shots(page)
        browser.close()


if __name__ == "__main__":
    main(sys.argv[1:])
