# -*- coding: utf-8 -*-
"""把 qc_shot 铺满所有建模镜，分批跑，结果并成一张表。

    python qc_all.py [跳过的镜,逗号分隔]

⛔ 分批（每批 12 镜）不是为了好看：一次性把 88 镜塞给一个 blender 进程，
   中途崩一次前面全白跑。分批之后崩了只丢一批，而且能接着跑。
⛔ 这张表是**筛子不是判据**：txtmin 只采 85% 那一帧，经常逮到正在弹出动画中途的
   标签，把好镜头报成低对比；clip 也会把「出生点在画外」的粒子算成出画。
   排完序还是要一镜一镜看图。
"""
import json, os, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.chdir(HERE)
import config as C  # noqa: E402
BLENDER = C.BLENDER
OUT = os.path.join(HERE, "work", "qcall.json")
SKIP = set((sys.argv[1].split(",") if len(sys.argv) > 1 else []))
T0 = time.time()

import grid as G

shots = [s for s in G.单位("画") if s not in SKIP]
print("要体检 %d 镜（跳过 %s）" % (len(shots), ",".join(sorted(SKIP)) or "无"), flush=True)

done = {}
if os.path.exists(OUT):
    done = {d["shot"]: d for d in json.load(open(OUT, encoding="utf-8"))}

BATCH = 12
for i in range(0, len(shots), BATCH):
    part = shots[i:i + BATCH]
    tmp = os.path.join(HERE, "work", "_qcpart.json")
    r = subprocess.run([BLENDER, "-b", "--python", os.path.join(HERE, "qc_shot.py"),
                        "--", tmp, ",".join(part)],
                       capture_output=True, text=True, errors="replace")
    got = 0
    if os.path.exists(tmp):
        for d in json.load(open(tmp, encoding="utf-8")):
            done[d["shot"]] = d
            got += 1
        os.remove(tmp)
    json.dump(list(done.values()), open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("[%5.0fs] %s → %d/%d 镜有数（本批 %d）"
          % (time.time() - T0, part[0] + "~" + part[-1], len(done), len(shots), got), flush=True)
    if got == 0:
        print(r.stdout[-1200:], flush=True)

rows = sorted(done.values(), key=lambda d: (d.get("txtmin") is not None and d["txtmin"], d["fillh"]))
print("\n可疑排序（对比度低 / 主体小 的排前面）：", flush=True)
print("镜    主体高  画内   字色   主体亮 地板抢", flush=True)
for d in rows[:24]:
    print("%-5s %.3f  %.3f  %-6s %.3f  %d"
          % (d["shot"], d["fillh"], d["clip"],
             ("%.3f" % d["txtmin"]) if d["txtmin"] is not None else "无字",
             d["subj"], d["floorhot"]), flush=True)
print("\nQC_ALL_DONE %d 镜" % len(done), flush=True)
