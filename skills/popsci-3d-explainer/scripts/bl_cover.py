# -*- coding: utf-8 -*-
"""封面底图（**示例**：中介层上一颗 GPU + 三栋 12 层 HBM，硅通孔发光）。换题材就整个重写这一份。

    blender.exe -b --python bl_cover.py -- <out.png>

出来的底图交给 cover.py 加 HUD 和标题 → 成品/<片名>_封面.png。
封面会被 final_pass 做成 1.5 秒缓推动画剪进片头，所以**构图要留出标题的位置**（左上压暗那一块）。
"""
import sys, os, math, bpy

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bl_lib as L

OUT = sys.argv[sys.argv.index("--") + 1] if "--" in sys.argv else os.path.join(HERE, "work", "cover_bg.png")

sc = L.reset(res=(1920, 1080), samples=192)
sc.world.node_tree.nodes["Background"].inputs[0].default_value = (0.006, 0.010, 0.018, 1)
sc.world.node_tree.nodes["Background"].inputs[1].default_value = 1.0

CY = (0.15, 0.9, 1.0, 1)
OR = (1.0, 0.55, 0.1, 1)

m_sub = L.mat("sub", (0.015, 0.022, 0.038, 1), metallic=0.1, rough=0.62)
m_die = L.mat("die", (0.05, 0.07, 0.10, 1), metallic=0.75, rough=0.30)
m_gpu = L.mat("gpu", (0.05, 0.065, 0.095, 1), metallic=0.7, rough=0.5)
m_tsv = L.mat("tsv", CY, emit=CY, emit_str=9.0)
m_tsv2 = L.mat("tsv2", CY, emit=CY, emit_str=3.5)
m_tr = L.mat("tr", CY, emit=CY, emit_str=1.6)
m_or = L.mat("or", OR, emit=OR, emit_str=1.7)
m_edge = L.mat("edge", CY, emit=CY, emit_str=2.0)

# 中介层（硅地板）
L.box("interposer", (9.0, 6.4, 0.16), (0, 0, 0), m_sub, bevel=0.02)
# 地板里的线路：一排排细发光条
for i in range(26):
    y = -3.0 + i * 0.24
    w = 3.4 if i % 3 else 4.2
    L.box("tr%d" % i, (w, 0.022, 0.012), (0.4, y, 0.085), m_tr)
for i in range(14):
    x = -3.9 + i * 0.62
    L.box("trv%d" % i, (0.02, 5.2, 0.012), (x, 0, 0.085), m_tr)

# GPU 大芯片：深色金属，顶面刻橙色计算阵列，只在四边留一圈细亮边
L.box("gpu", (3.5, 3.5, 0.34), (-2.3, 0, 0.25), m_gpu, bevel=0.03)
for i in range(9):
    L.box("gcore%d" % i, (2.9, 0.14, 0.010), (-2.3, -1.44 + i * 0.36, 0.423), m_or)
for i in range(9):
    L.box("gcorev%d" % i, (0.05, 2.9, 0.010), (-3.74 + i * 0.36, 0, 0.423), m_or)
for dx, dy, sx, sy in ((0, 1.76, 3.5, 0.04), (0, -1.76, 3.5, 0.04), (1.76, 0, 0.04, 3.5), (-1.76, 0, 0.04, 3.5)):
    L.box("ge%.1f_%.1f" % (dx, dy), (sx, sy, 0.014), (-2.3 + dx, dy, 0.424), m_edge)

# 三栋 12 层 HBM
LAY, TH, GAP = 12, 0.075, 0.038
for s, sx in enumerate((1.7, 3.3, 4.9)):
    base_z = 0.08
    L.box("base%d" % s, (1.25, 2.5, 0.12), (sx, 0, base_z + 0.06), m_gpu, bevel=0.01)
    for k in range(LAY):
        z = base_z + 0.12 + GAP + k * (TH + GAP) + TH / 2
        L.box("d%d_%d" % (s, k), (1.2, 2.4, TH), (sx, 0, z), m_die, bevel=0.006)
        L.box("g%d_%d" % (s, k), (1.24, 2.44, 0.006), (sx, 0, z - TH / 2 - GAP / 2), m_tsv2)
    top = base_z + 0.12 + GAP + LAY * (TH + GAP)
    # 硅通孔：贯穿整栋楼的发光铜柱
    for i in range(4):
        for j in range(7):
            L.cyl("tsv%d_%d_%d" % (s, i, j), 0.016, top - base_z - 0.1,
                  (sx - 0.42 + i * 0.28, -0.9 + j * 0.3, base_z + 0.1 + (top - base_z - 0.1) / 2), m_tsv)

# 对角线构图：GPU 在左下、三栋 HBM 在右上，左上留空给标题
cam = L.camera((-6.2, -9.6, 4.6), (0.9, 0, 1.0), lens=52, fstop=2.4, focus=11.4)
k, f, r = L.lights(key=430, fill=140, rim=2100)
k.location = (7.5, -3.0, 7.5); L.look(k, (2.5, 0, 0.8))

sc.render.filepath = OUT
os.makedirs(os.path.dirname(OUT), exist_ok=True)
bpy.ops.render.render(write_still=True)
print("COVER_BG", OUT)
