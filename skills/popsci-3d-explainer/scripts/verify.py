# -*- coding: utf-8 -*-
"""成片验收：十二条，全部落在**用户要打开的那个文件**上，每条给可复核的数字。

    python verify.py

⛔⛔ 第一道闸是 **mtime**：成片必须比最新的渲染帧 / 切片 / BGM 混音都新。
   「A 生成 B、下游只读 B」的地方如果不加这道闸，量的就是上一轮的产物——
   这条坑给过两轮假绿灯（看着全绿，其实验的是旧片）。
⛔ 每条都要有**数字或原文**。「看起来没问题」不算验收。
⛔ 我（模型）看不了动态画面、听不到声音：这里量的是能量化的部分，
   「画面好不好看」只能靠格子法一格一格亲眼看（grid.py + look.py）。
"""
import glob, json, os, re, subprocess, sys, tempfile, wave

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import config as C  # noqa: E402

FILM = os.path.join(HERE, "work", "film")
BL = os.path.join(HERE, "work", "blender")
FINAL = C.FINAL_MP4
TMP = tempfile.gettempdir()
SR = 16000
ok, bad = [], []


def 判(name, good, detail):
    (ok if good else bad).append((name, detail))
    print("%s %-22s %s" % ("✔" if good else "✘", name, detail), flush=True)


def probe(p, entries="format=duration", stream=None):
    cmd = ["ffprobe", "-v", "error", "-show_entries", entries, "-of", "csv=p=0"]
    if stream is not None:
        cmd += ["-select_streams", stream]
    return subprocess.check_output(cmd + [p], text=True).strip()


def wav_of(src, out, t0=None, t1=None):
    cmd = ["ffmpeg", "-y", "-v", "error"]
    if t0 is not None:
        cmd += ["-ss", "%.3f" % t0]
    cmd += ["-i", src]
    if t1 is not None:
        cmd += ["-t", "%.3f" % (t1 - t0)]
    subprocess.run(cmd + ["-ac", "1", "-ar", str(SR), "-vn", out], check=True)
    return out


def pcm(p):
    import numpy as np
    with wave.open(p, "rb") as w:
        x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
    return x


def main():
    import numpy as np

    # ① mtime 闸门 ------------------------------------------------------------
    assert os.path.exists(FINAL), "没有成片：" + FINAL
    tf = os.path.getmtime(FINAL)
    srcs = (glob.glob(os.path.join(BL, "*", "done.txt")) + glob.glob(os.path.join(FILM, "clips_h", "*.mp4"))
            + [os.path.join(FILM, "bgm_mix.mp3"), os.path.join(FILM, "subs.ass")])
    srcs = [s for s in srcs if os.path.exists(s)]
    newer = [os.path.basename(s) for s in srcs if os.path.getmtime(s) > tf + 1]
    判("① 成片是最新的", not newer,
      "成片 %s，比它新的上游 %d 个%s" % (__import__("time").strftime("%m-%d %H:%M", __import__("time").localtime(tf)),
                                 len(newer), ("：" + " ".join(newer[:6])) if newer else ""))

    # ② 时长与流 --------------------------------------------------------------
    dur = float(probe(FINAL))
    ad = float(probe(FINAL, "stream=duration", "a:0") or 0)
    ns = len(probe(FINAL, "stream=index").split())
    判("② 音视频等长", ns >= 2 and abs(ad - dur) < 0.35,
      "%d 条流 · 视频 %.2fs · 音频 %.2fs（差 %.2fs）" % (ns, dur, ad, abs(ad - dur)))
    # ⛔ 片尾没配音 ≠ 片尾没声音。amix 用 duration=first 会让整条音轨断在人声结束处，
    #    肉眼完全看不出来，只能 ffprobe 量流长度 + 量最后几秒的能量。

    # ③ 响度与真峰 ------------------------------------------------------------
    p = subprocess.run(["ffmpeg", "-i", FINAL, "-af", "ebur128=peak=true:framelog=quiet", "-f", "null", "-"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    I = float(re.search(r"I:\s+(-?[\d.]+) LUFS", p.stderr).group(1))
    TP = float(re.search(r"Peak:\s+(-?[\d.]+) dBFS", p.stderr).group(1))
    # ⛔ 量的是**整个文件**（平台也这么量），所以无配音的片尾也算在内。正片十几分钟时
    #    7~14 秒片尾摊薄后可忽略（实测 20 分钟片落在 -12.0，差 0.5 dB）；但拿几十秒的
    #    测试片跑这条会直接挂——0914 实测 14 秒正片配 14 秒片尾，整片 -16.7、正片段 -13.7。
    #    **短测试片上 ③ 不过是正常的**，别去改 TARGET_LUFS 或 BGM_V「修」它。
    判("③ 整片响度", abs(I - C.TARGET_LUFS) <= 1.2, "%.1f LUFS（目标 %.1f）" % (I, C.TARGET_LUFS))
    # ⛔⛔ 峰值和响度是两个**独立**验收项。采样峰被 alimiter 挡住了，AAC 编码后的峰间真峰
    #    照样能冲过 0，必须单独量 TP。
    判("④ 真峰不削顶", TP <= -0.3, "%.1f dBFS（线 ≤ -0.3）" % TP)

    # ④ 片尾不是死寂 ----------------------------------------------------------
    w = wav_of(FINAL, os.path.join(TMP, "_vtail.wav"), max(0, dur - 8), dur)
    x = pcm(w)
    tail_db = 20 * np.log10(float(np.sqrt(np.mean(x ** 2))) + 1e-12)
    判("⑤ 片尾有声音", tail_db > -45, "最后 8 秒 RMS %.1f dB" % tail_db)

    # ⑤ 逐分钟没有塌段 --------------------------------------------------------
    w = wav_of(FINAL, os.path.join(TMP, "_vall.wav"))
    x = pcm(w)
    per = []
    for k in range(int(len(x) / SR / 60) + 1):
        seg = x[k * 60 * SR:(k + 1) * 60 * SR]
        if seg.size < SR * 5:
            continue
        per.append(20 * np.log10(float(np.sqrt(np.mean(seg ** 2))) + 1e-12))
    med = float(np.median(per)) if per else 0.0
    low = [(i, v) for i, v in enumerate(per) if v < med - 6]
    判("⑥ 没有塌掉的分钟", not low,
      "逐分钟 RMS 中位 %.1f dB，最低 %.1f dB%s" % (med, min(per) if per else 0,
                                          ("，塌段：" + " ".join("第%d分" % (i + 1) for i, _ in low)) if low else ""))

    # ⑥ 每镜帧数 == beats.N ---------------------------------------------------
    b = json.load(open(os.path.join(FILM, "beats.json"), encoding="utf-8"))
    mism = []
    for seg, v in b.items():
        d = os.path.join(BL, seg[:-1], "done.txt")
        n = int(open(d).read().strip() or 0) if os.path.exists(d) else -1
        # ⛔⛔ 判据必须是「恰好相等」，不是「够就行」。段落变短时旧帧数反而更大，
        #    `chain.render` 的「帧数够就跳过」会把整段静默跳过，画面停在旧拍点上。
        if n != v["N"]:
            mism.append("%s %d≠%d" % (seg[:-1], n, v["N"]))
    判("⑦ 帧数对齐拍点", not mism, "%d 镜，不符 %d 处%s" % (len(b), len(mism), ("：" + " ".join(mism[:8])) if mism else ""))

    # ⑦ 两道渲染前闸门 --------------------------------------------------------
    for g, key in (("check_scenes.py", "CHECK_OK"), ("check_beats_kw.py", "KW_OK")):
        r = subprocess.run([C.PY_AUDIO, "-X", "utf8", os.path.join(HERE, g)],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        判("⑧ " + g, key in r.stdout, r.stdout.strip().splitlines()[-1] if r.stdout.strip() else "无输出")

    # ⑧ 吞音闸门 --------------------------------------------------------------
    r = subprocess.run([C.PY_AUDIO, "-X", "utf8", os.path.join(HERE, "pauses.py"), "check"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    判("⑨ 自插停顿没吞音", "PAUSE_CHECK_OK" in r.stdout,
      (r.stdout.strip().splitlines() or ["无输出"])[-2 if len(r.stdout.strip().splitlines()) > 1 else -1])

    # ⑨ 字幕 ------------------------------------------------------------------
    ass = os.path.join(FILM, "subs.ass")
    lines = [l for l in open(ass, encoding="utf-8-sig").read().splitlines() if l.startswith("Dialogue")]
    subs = [l.split(",,")[-1] for l in lines if ",Sub," in l]
    txt = [re.sub(r"\{[^}]*\}", "", s) for s in subs]
    longest = max((len(t) for t in txt), default=0)
    head_punct = [t for t in txt if t and t[0] in "，。！？；：、"]
    判("⑩ 字幕不超宽不倒标点", longest <= 20 and not head_punct,
      "%d 条 · 最长 %d 字 · 以标点开头 %d 条" % (len(txt), longest, len(head_punct)))

    # ⑩ 章节进度条边界单调 ----------------------------------------------------
    xs = [int(m.group(1)) for l in lines if ",BarTxt," in l for m in [re.search(r"\\pos\((\d+),", l)] if m]
    mono = all(xs[i] <= xs[i + 1] for i in range(len(xs) - 1)) if xs else False
    判("⑪ 章节条单调", mono, "章名 x 坐标 %s" % xs[:12])

    # ⑪ 素材零复用 ------------------------------------------------------------
    import shots as SB
    seen, dup = {}, []
    for sc in SB.SCENES:
        for sh in sc["visual"]["shots"]:
            for k in ("seg", "real"):
                if k in sh:
                    key = k + ":" + sh[k]
                    if key in seen:
                        dup.append("%s (%s→%s)" % (key, seen[key], sc["id"]))
                    seen[key] = sc["id"]
    判("⑫ 素材零复用", not dup, "%d 个素材位%s" % (len(seen), ("，复用：" + " ".join(dup[:5])) if dup else ""))

    print("\n%d 过 / %d 不过" % (len(ok), len(bad)))
    if bad:
        print("VERIFY_FAIL")
        for n, d in bad:
            print("  ✘ %s  %s" % (n, d))
        return 1
    print("VERIFY_OK  →  " + FINAL)
    return 0


if __name__ == "__main__":
    sys.exit(main())
