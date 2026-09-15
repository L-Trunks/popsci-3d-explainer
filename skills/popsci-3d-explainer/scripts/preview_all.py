# -*- coding: utf-8 -*-
"""全部 85 镜跑一遍低清预览 + 自动空场检查（beat-driven-explainer 的量化 QC）。

    python preview_all.py           渲染 + 检查
    python preview_all.py qc        只检查已有预览
    python preview_all.py sheet     拼联络表（每镜取第 1 帧和中间帧）

判据：① 第 1 帧必须有主角（内容占比 ≥ 1.5%）② 全镜没有连续 ≥3 个预览帧near空
       ③ 最大连通亮块高度 ≥ 画面高 1/4（主角 ≥ 1/3 的低清近似）
"""
import glob, json, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import config as C  # noqa: E402

BLENDER = C.BLENDER
PREV = os.path.join(HERE, "work", os.environ.get("PREV_DIR", "preview"))


def shot_list():
    import re, io
    out = []
    for f in C.shot_paths():
        out += re.findall(r"^def (S\d+)\(", io.open(f, encoding="utf-8").read(), re.M)
    return sorted(out, key=lambda s: int(s[1:]))


def render():
    env = dict(os.environ, BEATS_JSON=os.path.join(HERE, "work", "film", "beats.json"), BL_STEP="20")
    for s in shot_list():
        d = os.path.join(PREV, s)
        if os.path.isdir(d) and glob.glob(os.path.join(d, "*.png")):
            continue
        r = subprocess.run([BLENDER, "-b", "--python", C.SHOT_ENTRY, "--", s, d, "preview"],
                           capture_output=True, text=True, errors="replace", env=env)
        ok = "RENDER_DONE" in r.stdout
        print("%-5s %s" % (s, "ok" if ok else "FAIL " + r.stdout[-400:].replace("\n", " ")), flush=True)


def qc():
    from PIL import Image
    import numpy as np
    bad = []
    for s in shot_list():
        fs = sorted(glob.glob(os.path.join(PREV, s, "*.png")))
        if not fs:
            bad.append((s, "无预览")); continue
        fr = []
        for f in fs:
            a = np.asarray(Image.open(f).convert("L"), dtype=np.float32) / 255.0
            m = a > 0.10
            frac = m.mean()
            rows = m.sum(axis=1)
            h = (rows > a.shape[1] * 0.012).sum() / a.shape[0]      # 有内容的行占比 ≈ 主角高度
            fr.append((frac, h))
        msgs = []
        if fr[0][0] < 0.015:
            msgs.append("第1帧空场 %.1f%%" % (fr[0][0] * 100))
        run = mx = 0
        for f0, _ in fr:
            run = run + 1 if f0 < 0.012 else 0
            mx = max(mx, run)
        if mx >= 3:
            msgs.append("连续 %d 个预览帧空" % mx)
        if max(h for _, h in fr) < 0.25:
            msgs.append("主角过小 max高度 %.0f%%" % (max(h for _, h in fr) * 100))
        if msgs:
            bad.append((s, " / ".join(msgs)))
    for s, m in bad:
        print("!! %-5s %s" % (s, m))
    print("QC: %d/%d 有问题" % (len(bad), len(shot_list())))
    json.dump([b[0] for b in bad], open(os.path.join(PREV, "_bad.json"), "w"))


def sheet():
    from PIL import Image, ImageDraw
    ss = shot_list()
    W, H, C = 320, 180, 8
    rows = (len(ss) * 2 + C - 1) // C
    im = Image.new("RGB", (W * C, H * rows), (0, 0, 0)); d = ImageDraw.Draw(im)
    k = 0
    for s in ss:
        fs = sorted(glob.glob(os.path.join(PREV, s, "*.png")))
        if not fs:
            continue
        for f in (fs[0], fs[len(fs) // 2]):
            t = Image.open(f).convert("RGB").resize((W, H))
            im.paste(t, ((k % C) * W, (k // C) * H))
            d.text(((k % C) * W + 6, (k // C) * H + 4), s, fill=(255, 210, 60))
            k += 1
    p = os.path.join(PREV, "sheet_all.png"); im.save(p); print("sheet", p, k, "tiles")


if __name__ == "__main__":
    a = sys.argv[1] if len(sys.argv) > 1 else "all"
    if a in ("all", "render"):
        render()
    if a in ("all", "qc"):
        qc()
    if a == "sheet":
        sheet()
