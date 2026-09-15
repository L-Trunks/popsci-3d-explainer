# -*- coding: utf-8 -*-
"""实测数据 → 动态图表视频（深色，和卡片同配色）。

    python chart.py rand4k  work/bench/quick.json out.mp4 [dur]   # 三盘 4K 随机读 IOPS 柱状图长出来
    python chart.py seq     work/bench/quick.json out.mp4 [dur]   # 三盘顺序读写 MB/s 柱状
    python chart.py cliff   work/bench/cliff_C.json out.mp4 [dur] # 连续写吞吐曲线从左到右画出来
"""
import json, sys, os, subprocess
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

W, H, FPS = 1920, 1080, 30
BG = "#090e16"; AC = "#3ae6ff"; OR = "#ff8c1a"; TXT = "#eef4fa"; MUTED = "#96aabe"; RED = "#ff4d3d"
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import config as _C
fp = font_manager.FontProperties(fname=_C.FONT_UI)
plt.rcParams["font.family"] = fp.get_name()
plt.rcParams["axes.unicode_minus"] = False
NAMES = {"C": "ZHITAI NVMe 1TB", "E": "Fanxiang NVMe 4TB", "G": "WD 机械硬盘 2TB"}


def fig_base(title):
    fig = plt.figure(figsize=(W / 100, H / 100), dpi=100, facecolor=BG)
    ax = fig.add_axes([0.1, 0.16, 0.84, 0.66], facecolor=BG)
    for s in ax.spines.values():
        s.set_color("#243448")
    ax.tick_params(colors=MUTED, labelsize=22)
    ax.grid(color="#16222f", linewidth=1)
    fig.text(0.1, 0.9, title, color=TXT, fontsize=40, fontproperties=fp, fontweight="bold")
    return fig, ax


def ease(t):
    return t * t * (3 - 2 * t)


def stream(frames, out):
    p = subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "%dx%d" % (W, H), "-r", str(FPS), "-i", "-",
                          "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", out], stdin=subprocess.PIPE)
    for f in frames:
        p.stdin.write(f)
    p.stdin.close(); p.wait()


def fig_bytes(fig):
    fig.canvas.draw()
    return np.asarray(fig.canvas.buffer_rgba())[:, :, :3].tobytes()


def bars(data, keys, title, ylabel, dur, out, colors, fmt="{:,.0f}", log=False):
    N = int(dur * FPS); frames = []
    vals = [data[k] for k in keys]; labels = [NAMES.get(k, k) for k in keys]
    for i in range(N):
        t = ease(min(1.0, i / (FPS * 2.0)))
        fig, ax = fig_base(title)
        cur = [v * t for v in vals]
        b = ax.bar(labels, cur, color=colors, width=0.55)
        if log:
            ax.set_yscale("log"); ax.set_ylim(1, max(vals) * 3)
        else:
            ax.set_ylim(0, max(vals) * 1.25)
        ax.set_ylabel(ylabel, color=MUTED, fontsize=24, fontproperties=fp)
        for rect, v in zip(b, cur):
            ax.text(rect.get_x() + rect.get_width() / 2, rect.get_height() * (1.15 if log else 1) + (0 if log else max(vals) * 0.02),
                    fmt.format(v), ha="center", color=TXT, fontsize=34, fontproperties=fp, fontweight="bold")
        for lab in ax.get_xticklabels():
            lab.set_fontproperties(fp); lab.set_fontsize(26); lab.set_color(TXT)
        frames.append(fig_bytes(fig)); plt.close(fig)
    stream(frames, out); print(out, N)


def cliff(js, dur, out):
    s = js["samples"]; t = np.array([x[0] for x in s]); mb = np.array([x[1] for x in s]); gb = np.array([x[2] for x in s])
    k = max(1, len(mb) // 200)
    N = int(dur * FPS); frames = []
    for i in range(N):
        prog = ease(min(1.0, i / (FPS * (dur - 2.0))))
        n = max(2, int(len(gb) * prog))
        fig, ax = fig_base("连续往 %s 盘写入：写入速度 vs 已写入量" % NAMES.get(js["drive"], js["drive"]))
        ax.plot(gb[:n], mb[:n], color=AC, linewidth=3)
        ax.fill_between(gb[:n], 0, mb[:n], color=AC, alpha=0.12)
        ax.set_xlim(0, gb[-1] * 1.02); ax.set_ylim(0, mb.max() * 1.2)
        ax.set_xlabel("已写入 (GB)", color=MUTED, fontsize=24, fontproperties=fp); ax.set_ylabel("MB/s", color=MUTED, fontsize=24, fontproperties=fp)
        near_end = gb[n - 1] > gb[-1] * 0.8
        ax.text(gb[n - 1], mb[n - 1] + mb.max() * 0.05, "%.0f MB/s" % mb[n - 1], color=TXT, fontsize=30, fontproperties=fp, fontweight="bold", ha="right" if near_end else "left")
        frames.append(fig_bytes(fig)); plt.close(fig)
    stream(frames, out); print(out, N)


if __name__ == "__main__":
    kind, src, out = sys.argv[1], sys.argv[2], sys.argv[3]
    dur = float(sys.argv[4]) if len(sys.argv) > 4 else 8.0
    js = json.load(open(src))
    if kind == "rand4k":
        bars({k: js[k]["rand4k_iops"] for k in js}, ["G", "E", "C"], "4K 随机读：每秒能完成多少次「找一小块数据」", "IOPS（次/秒）", dur, out, [RED, OR, AC], log=True)
    elif kind == "seq":
        bars({k: js[k]["read_mbps"] for k in js}, ["G", "E", "C"], "顺序读：大文件一口气读", "MB/s", dur, out, [RED, OR, AC])
    elif kind == "seqw":
        bars({k: js[k]["write_mbps"] for k in js}, ["G", "E", "C"], "顺序写：大文件一口气写", "MB/s", dur, out, [RED, OR, AC])
    elif kind == "cliff":
        cliff(js, dur, out)
