"""Matplotlib helpers (imported lazily so the protocol itself needs no deps)."""

from __future__ import annotations

import math

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

PALETTE = ["#2563eb", "#dc2626", "#16a34a", "#9333ea", "#ea580c", "#0891b2", "#4b5563"]


def _style(ax, title, xlabel, ylabel):
    ax.set_title(title, fontsize=12, fontweight="bold")
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.grid(True, alpha=0.3)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)


def line_plot(path, x, series: dict, title, xlabel, ylabel, theory: dict | None = None,
              logy=False, xticks=None, percent_x=False):
    fig, ax = plt.subplots(figsize=(8, 4.8))
    for k, (label, ys) in enumerate(series.items()):
        ax.plot(x, ys, marker="o", lw=2, ms=5, label=label, color=PALETTE[k % len(PALETTE)])
    for k, (label, spec) in enumerate((theory or {}).items()):
        tx, ty = spec[0], spec[1]
        color = PALETTE[spec[2] % len(PALETTE)] if len(spec) > 2 else PALETTE[k % len(PALETTE)]
        ax.plot(tx, ty, ls="--", lw=1.4, label=label, color=color, alpha=0.7)
    if logy:
        ax.set_yscale("log")
    if xticks is not None:
        ax.set_xticks(xticks)
    if percent_x:
        ax.set_xticks(x)
        ax.xaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0, decimals=0))
    _style(ax, title, xlabel, ylabel)
    ax.legend(fontsize=8, frameon=False)
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)


def cwnd_plot(path, traces: dict, title="Congestion window over time", queue_line=None):
    fig, ax = plt.subplots(figsize=(10, 4.8))
    for k, (label, tr) in enumerate(traces.items()):
        pts = [(t, c) for t, c, s, st in tr["cwnd"] if c is not None]
        if not pts:
            continue
        ts, cs = zip(*pts)
        ax.step(ts, cs, where="post", lw=1.6, label=f"{label} cwnd", color=PALETTE[k])
        ss = [(t, s) for t, c, s, st in tr["cwnd"] if s is not None and s < 1e6]
        if ss:
            st_, sv = zip(*ss)
            ax.step(st_, sv, where="post", lw=1, ls=":", color=PALETTE[k], label=f"{label} ssthresh")
        for t, kind, _ in tr["events"]:
            ax.axvline(t, color=PALETTE[k], alpha=0.12 if kind == "fastretx" else 0.3,
                       lw=0.8, ls="-" if kind == "timeout" else "--")
    if queue_line:
        ax.axhline(queue_line, color="#6b7280", ls="-.", lw=1, label="BDP + queue (pipe size)")
    _style(ax, title, "time (s)", "window (packets)")
    ax.legend(fontsize=8, frameon=False, ncol=2)
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)


def seq_time_plot(path, traces: dict, title="Sequence number vs time"):
    n = len(traces)
    fig, axes = plt.subplots(1, n, figsize=(6 * n, 4.8), sharey=True, squeeze=False)
    for ax, (label, tr) in zip(axes[0], traces.items()):
        new = [(t, i) for t, i, r in tr["sends"] if not r]
        rtx = [(t, i) for t, i, r in tr["sends"] if r]
        if new:
            ax.scatter(*zip(*new), s=6, color="#2563eb", label="new packet")
        if rtx:
            ax.scatter(*zip(*rtx), s=10, color="#dc2626", marker="x", label="retransmission")
        if tr["acks"]:
            ta, ba = zip(*tr["acks"])
            ax.step(ta, [b - 1 for b in ba], where="post", color="#16a34a", lw=1, label="cumulative ACK")
        for t, kind, _ in tr["events"]:
            if kind == "timeout":
                ax.axvline(t, color="#dc2626", alpha=0.25, lw=0.8)
        _style(ax, f"{label}  ({len(rtx)} retransmissions)", "time (s)", "packet index")
        ax.legend(fontsize=8, frameon=False, loc="upper left")
    fig.suptitle(title, fontweight="bold")
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)


def rtt_plot(path, trace: dict, title="RTT estimation (Jacobson/Karels)"):
    if not trace["rtt"]:
        return
    t, sample, srtt, rto = zip(*trace["rtt"])
    fig, ax = plt.subplots(figsize=(10, 4.2))
    ax.scatter(t, [s * 1000 for s in sample], s=5, color="#9ca3af", label="RTT sample")
    ax.plot(t, [s * 1000 for s in srtt], color="#2563eb", lw=1.8, label="SRTT")
    ax.plot(t, [r * 1000 for r in rto], color="#dc2626", lw=1.4, label="RTO = SRTT + 4·RTTVAR (min 200 ms)")
    _style(ax, title, "time (s)", "milliseconds")
    ax.legend(fontsize=8, frameon=False)
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)


def bar_plot(path, labels, groups: dict, title, ylabel, logy=False):
    fig, ax = plt.subplots(figsize=(9, 4.6))
    n = len(groups)
    w = 0.8 / n
    for k, (name, vals) in enumerate(groups.items()):
        xs = [i + (k - (n - 1) / 2) * w for i in range(len(labels))]
        plot_vals = [max(v, 1e-6) if logy else v for v in vals]
        ax.bar(xs, plot_vals, w, label=name, color=PALETTE[k])
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=20, ha="right", fontsize=8)
    if logy:
        ax.set_yscale("log")
    _style(ax, title, "", ylabel)
    ax.legend(fontsize=8, frameon=False)
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)


def nan_to_none(v):
    return None if v is None or (isinstance(v, float) and math.isnan(v)) else v
