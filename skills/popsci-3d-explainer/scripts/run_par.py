# -*- coding: utf-8 -*-
"""并行渲染的一份：一个进程啃一份**互不相交**的镜头清单。

    python run_par.py S05,S45,S46,S47

起三个进程就开三个窗口各跑一份清单（一律 detached，别挂在会话里）：
    Start-Process -WindowStyle Hidden python -ArgumentList "run_par.py S01,S02,..." -RedirectStandardOutput a.log

⛔ 别用「两个进程啃同一条队列」的写法：交接靠的是 done.txt，而 done.txt 是**完工才写**的，
   于是还得自己去看目录在不在被别人写。按镜头分堆，清单没有交集，压根不会撞。
⭐ 实测吞吐：2 进程 1.60×、3 进程 1.81×（边际很薄，再加意义不大）。
   瓶颈不是算力——GPU 利用率 73% 但功耗只有 125W/310W，卡在同步延迟上。
⛔ 已经有帧的镜头（要重渲的那些）先把帧挪进回收站，不然 chain.render 看见 done.txt 就跳过了。
⛔ 判「还在不在跑」看**产物 mtime**（work/blender/S*/*.png 里最新那个），别看进程、别看计数
   ——一个 400 帧的镜头能渲 20 分钟，按计数判会误报成卡死。
"""
import os, shutil, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.chdir(HERE)
import config as C  # noqa: E402

BL = os.path.join(HERE, "work", "blender")
BAK = os.path.join(C.TRASH, time.strftime("%m%d") + "-" + C.TITLE + "-重渲前")

shots = [s.strip() for s in sys.argv[1].split(",") if s.strip()]
os.makedirs(BAK, exist_ok=True)
print("空间还剩 %.1f GB" % C.assert_disk(), flush=True)
T0 = time.time()
for s in shots:
    moved = False
    for p in (os.path.join(BL, s), os.path.join(BL, s + ".mp4")):
        if os.path.exists(p):
            dst = os.path.join(BAK, os.path.basename(p))
            if os.path.exists(dst):
                dst += "_%d" % int(time.time())
            shutil.move(p, dst); moved = True
    print(("挪走 " if moved else "新镜 ") + s, flush=True)

import chain
chain.render(only=set(shots))
print("PAR_OK %s  %.0fs" % (" ".join(shots), time.time() - T0), flush=True)
