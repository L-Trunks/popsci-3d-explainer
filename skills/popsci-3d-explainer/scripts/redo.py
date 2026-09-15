# -*- coding: utf-8 -*-
"""重渲指定的几镜（改过某一镜之后用）。

    python redo.py S03,S05

⛔ chain.render 看 done.txt 跳过已渲的，所以要先把那几镜的帧挪走（**不是删**，
   一律进 _废弃回收）。挪完再渲。
"""
import os, shutil, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.chdir(HERE)
import config as C  # noqa: E402
BL = os.path.join(HERE, "work", "blender")
# ⛔ 每一批重渲用自己的日期目录：混在一个目录里，出事时分不清哪一版是哪一批的。
# ⛔ 废弃产物**只搬不删**——查回归时要拿旧帧和新帧对照（「这处压字是不是本轮弄坏的」
#    只能这么判）。跨盘搬 PNG 序列是小文件海，实测机械盘只有 55 MB/s，别在开渲前一刻才清。
BAK = os.path.join(C.TRASH, time.strftime("%m%d") + "-" + C.TITLE + "-单镜重渲前")

shots = [s.strip() for s in sys.argv[1].split(",") if s.strip()]
os.makedirs(BAK, exist_ok=True)
for s in shots:
    for p in (os.path.join(BL, s), os.path.join(BL, s + ".mp4")):
        if os.path.exists(p):
            dst = os.path.join(BAK, os.path.basename(p))
            if os.path.exists(dst):
                dst += "_%d" % int(time.time())
            shutil.move(p, dst)
    print("挪走", s, flush=True)
import chain
chain.render(only=set(shots))
print("REDO_OK", " ".join(shots), flush=True)
