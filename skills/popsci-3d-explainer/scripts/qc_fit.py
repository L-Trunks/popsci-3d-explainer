# -*- coding: utf-8 -*-
"""取景检查器：不渲染，只把每镜的物体投影到画面坐标，算「建模有多少落在画内」。

    blender.exe -b --python qc_fit.py -- [S11,S12 | all]

判据（用户 0911：「完整的建模只能看到 70%」）：
  画率  = 主体外接框落在画内的面积 / 外接框总面积   ——  < 0.92 就是出画
  主体高 = 主体外接框在画面里的高度占比            ——  < 0.33 是主角太小（a2e 口径）
  标签   = 文字物体必须整个在画内，且离边 ≥ 2%
中途飞入/飞出的物体会在个别帧出画，所以按**采样帧的中位数**判，不看单帧最差。
"""
import json, os, sys

import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bl_lib as L  # noqa: E402

L.render = lambda *a, **kw: None          # 只搭场景，不出图
import shotload  # noqa: E402

SHOTS = shotload.load()
SKIP = ("floor", "bg", "backdrop")        # 地板类本来就该铺满出画


def _corners(ob):
    mw = ob.matrix_world
    return [mw @ Vector(c) for c in ob.bound_box]


def _ndc(sc, cam, pts):
    out = []
    for p in pts:
        v = world_to_camera_view(sc, cam, p)
        out.append((v.x, v.y, v.z))
    return out


def measure(sc, cam):
    """返回 (画率, 主体高占比, 出画物体列表, 越界标签列表)。判据和 bs.fit 用同一套。"""
    import bl_scene as bs
    bad = {}; lab = []
    for ob in sc.objects:
        try:
            if ob.hide_render or ob.type not in ("MESH", "FONT"):
                continue
            if any(ob.name.lower().startswith(s) for s in SKIP):
                continue
            pts = _ndc(sc, cam, _corners(ob))
        except Exception:                 # 上一镜留下的失效数据块（VectorFont removed 等）
            continue
        if any(p[2] <= 0 for p in pts):       # 在相机背后
            continue
        x0 = min(p[0] for p in pts); x1 = max(p[0] for p in pts)
        y0 = min(p[1] for p in pts); y1 = max(p[1] for p in pts)
        cx = (x0 + x1) / 2; cy = (y0 + y1) / 2
        if not (-0.05 <= cx <= 1.05 and -0.05 <= cy <= 1.05):
            continue                          # 此刻不在画面里的东西不算（横移镜头的下一站）
        if ob.type == "FONT":
            # 被前面的几何体挡住：从相机往标签中心打一条射线，撞到别的东西就是挡了
            try:
                dg = bpy.context.evaluated_depsgraph_get()
                o = cam.matrix_world.translation
                c = ob.matrix_world.translation
                v = (c - o); dist = v.length; v.normalize()
                hit, loc, _, _, obj, _ = sc.ray_cast(dg, o + v * 0.05, v)
                if hit and obj and obj.name != ob.name and (loc - o).length < dist - 0.25:
                    lab.append(ob.name + "·被挡(" + obj.name + ")")
                    continue
            except Exception:
                pass
            if x0 < 0.02 or x1 > 0.98 or y0 < 0.02 or y1 > 0.98:
                lab.append(ob.name)
            # ⛔ 字幕带（MarginV 120 + 60 号字，约画面底部 7%~22%）里不许有 3D 标签，会和字幕叠在一起
            elif y0 < 0.23 and y1 > 0.06 and x1 > 0.18 and x0 < 0.82:
                lab.append(ob.name + "·压字幕")
            continue
        w = max(x1 - x0, 1e-6) * max(y1 - y0, 1e-6)
        ix = max(0.0, min(x1, 1.0) - max(x0, 0.0)); iy = max(0.0, min(y1, 1.0) - max(y0, 0.0))
        r = max(0.0, ix) * max(0.0, iy) / w
        if r < 0.999:
            bad[ob.name] = r
    r = bs._content(sc, cam)
    if not r:
        return 1.0, 0.0, bad, lab
    X0, X1, Y0, Y1 = r[0]
    area = max(X1 - X0, 1e-6) * max(Y1 - Y0, 1e-6)
    ix = max(0.0, min(X1, 1.0) - max(X0, 0.0)); iy = max(0.0, min(Y1, 1.0) - max(Y0, 0.0))
    # 主角大小取「高 或 宽×9/16」的大者：平摊的东西（晶圆、中介层、井阵列）高度天生小，
    # 只看高度会把拍得很满的俯视镜头误判成主角太小。
    return ix * iy / area, max(iy, ix * 9 / 16.0), bad, lab


def one(shot):
    L._font = None          # read_factory_settings 会清掉字体数据块，模块级缓存必须跟着作废
    SHOTS[shot](os.path.join(HERE, "work", "qcfit"), True)
    sc = bpy.context.scene
    cam = sc.camera
    N = sc.frame_end
    fits = []; hs = []; badn = {}; labs = set()
    for f in [max(1, int(N * t)) for t in (0.08, 0.3, 0.5, 0.7, 0.95)]:
        sc.frame_set(f)
        fit, h, bad, lab = measure(sc, cam)
        fits.append(fit); hs.append(h)
        for k, v in bad.items():
            badn[k] = min(badn.get(k, 1.0), v)
        labs |= set(lab)
    fits.sort(); hs.sort()
    nf = sum(1 for o in sc.objects if o.type == "FONT")
    sc.frame_set(max(1, int(N * 0.75)))
    import bpy as _b; _b.context.view_layer.update()
    sig = [round(v, 3) for v in cam.matrix_world.translation]
    for o in sorted(sc.objects, key=lambda x: x.name):
        if o.type == "FONT":
            sig += [round(v, 3) for v in o.matrix_world.translation]
    return dict(shot=shot, fit=round(fits[len(fits) // 2], 3), hero=round(hs[len(hs) // 2], 3),
                worst=round(fits[0], 3), nfont=nf, sig=sig,
                bad=sorted(badn.items(), key=lambda kv: kv[1])[:6], labels=sorted(labs))


def main():
    a = sys.argv[sys.argv.index("--") + 1:]
    want = sorted(SHOTS) if (not a or a[0] == "all") else a[0].split(",")
    rows = []
    for s in want:
        try:
            rows.append(one(s))
        except Exception as e:
            rows.append(dict(shot=s, fit=-1, hero=-1, worst=-1, bad=[], labels=[], err=str(e)[:120]))
        r = rows[-1]
        flag = "出画" if 0 <= r["fit"] < 0.92 else ("小" if 0 <= r["hero"] < 0.33 else "ok")
        print("%-5s 画率 %-6s 主体高 %-6s %s %s %s" % (r["shot"], r["fit"], r["hero"], flag,
              " ".join("%s:%.2f" % (k, v) for k, v in r["bad"][:3]), ("标签出框:" + ",".join(r["labels"])) if r["labels"] else ""), flush=True)
    p = os.path.join(HERE, "work", "qc_fit.json")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    json.dump(rows, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    n1 = sum(1 for r in rows if 0 <= r["fit"] < 0.92)
    n2 = sum(1 for r in rows if 0 <= r["hero"] < 0.33)
    print("\n合计 %d 镜：出画 %d · 主角偏小 %d · 标签出框 %d" % (len(rows), n1, n2, sum(1 for r in rows if r["labels"])))


main()
