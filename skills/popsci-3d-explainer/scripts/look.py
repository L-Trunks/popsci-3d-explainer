# -*- coding: utf-8 -*-
"""把指定镜头的关键帧渲成看得清的图，给人眼看。格子法的「亲眼看这一格」就靠它。

    blender.exe -b --python look.py -- <输出目录> S70,S74,S80 [宽度]

默认 960×540、每镜 3 帧（25% / 55% / 85%），全质量（开光追和阴影，和成片一致）。
"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bpy  # noqa: E402
import bl_lib as L  # noqa: E402
import shotload  # noqa: E402

_cap = {}


def load():
    return shotload.load()


if __name__ == "__main__":
    a = sys.argv[sys.argv.index("--") + 1:]
    outd, names = a[0], a[1].split(",")
    W = int(a[2]) if len(a) > 2 else 960
    os.makedirs(outd, exist_ok=True)
    S = load()
    real = L.render
    for n in names:
        if n not in S:
            print("!! 没有", n, flush=True); continue
        L._font = None

        def fake(sc, out_dir, start=None, end=None):
            _cap["sc"] = sc; _cap["N"] = end or 240
        L.render = fake
        try:
            S[n](os.path.join(outd, "_"), False)
        finally:
            L.render = real
        sc = _cap["sc"]; N = _cap["N"]
        sc.render.resolution_x, sc.render.resolution_y = W, int(W * 9 / 16)
        sc.render.resolution_percentage = 100
        for i, t in enumerate((0.25, 0.55, 0.9)):
            sc.frame_set(max(1, min(N, int(round(N * t)))))
            sc.render.filepath = os.path.join(outd, "%s_%d" % (n, i))
            bpy.ops.render.render(write_still=True)
        print("looked", n, flush=True)
    print("LOOK_DONE", flush=True)
