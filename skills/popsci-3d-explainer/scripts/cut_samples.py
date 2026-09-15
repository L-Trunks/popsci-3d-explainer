# -*- coding: utf-8 -*-
"""从成片切样片（给用户先看片段，不用等 20 分钟看完）。

    python cut_samples.py

清单写在 config.json 的 samples 里，每条三选一：
    {"name": "样片_开场",   "head": 45}          从头切 45 秒
    {"name": "样片_厮杀",   "seg": "p02"}        某一段整段
    {"name": "样片_结尾",   "seg": "LAST"}       最后一段到片尾（含静默片尾）

⛔⛔ 切点**不许手写秒数**：按 storyboard 的段时长算，改稿之后自动跟着走。
   手写过一次，改稿后没人知道那个「样片_厮杀开场」当初是从哪儿切的。
⛔ 切完必须 ffprobe 数流：带分辨率后缀的成片曾经**没有音轨**，肉眼看不出来。
"""
import json, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.stdout.reconfigure(encoding="utf-8")
import config as C  # noqa: E402

FILM = os.path.join(HERE, "work", "film")
OUT = C.OUTDIR
SRC = C.FINAL_MP4
COVER_OFF = 1.5 - 0.3          # 封面接进来的偏移：成片时间 = 正片时间 + 这个（和 final_pass 的 COVER_DUR/XF 一致）


def probe(p, key="format=duration"):
    return subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", key,
                                    "-of", "csv=p=0", p], text=True).strip()


def seg_times():
    """每一段在**正片**里的起止秒（按 clips_h 的实际时长累加，和 subs.py 同口径）。"""
    cfg = json.load(open(os.path.join(FILM, "storyboard.json"), encoding="utf-8"))
    T = float(cfg.get("transition", 0) or 0)
    cdir = os.path.join(FILM, "clips_h")
    out, t = {}, 0.0
    for i, s in enumerate(cfg["scenes"]):
        d = float(probe(os.path.join(cdir, s["id"] + ".mp4")))
        if i:
            t -= T
        out[s["id"]] = (t, t + d)
        t += d
    out["LAST"] = out[cfg["scenes"][-1]["id"]]
    return out


def cut(name, t0, t1, why):
    dst = os.path.join(OUT, name if name.endswith(".mp4") else name + ".mp4")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", "%.3f" % t0, "-i", SRC,
                    "-t", "%.3f" % (t1 - t0), "-c:v", "libx264", "-preset", "medium", "-crf", "18",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "256k", dst], check=True)
    ns = len(probe(dst, "stream=index").split())
    assert ns >= 2, "⛔ %s 只有 %d 条流——八成丢了音轨" % (name, ns)
    print("%-28s %6.1f~%6.1f s  %5.1f MB  %d 条流   %s"
          % (name, t0, t1, os.path.getsize(dst) / 1e6, ns, why))


def main():
    assert os.path.exists(SRC), "没有成片：" + SRC
    total = float(probe(SRC))
    st = seg_times()
    print("成片 %.1f 分钟\n" % (total / 60))
    if not C.SAMPLES:
        print("config.json 的 samples 是空的，没有要切的样片"); return
    for s in C.SAMPLES:
        if "head" in s:
            cut(s["name"], 0.0, float(s["head"]), "开头 %s 秒" % s["head"])
        elif s.get("seg") == "LAST":
            a, _ = st["LAST"]
            cut(s["name"], a + COVER_OFF, total, "最后一段 + 静默片尾")
        else:
            a, b = st[s["seg"]]
            cut(s["name"], a + COVER_OFF, b + COVER_OFF, "%s 整段" % s["seg"])
    print("\n全部落在：" + OUT)


main()
