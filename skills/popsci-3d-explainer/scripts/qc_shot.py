# -*- coding: utf-8 -*-
"""镜头级量化体检（在 Blender 里跑）：取景 · 光 · 字色，三件一次量完。

    blender.exe -b --python qc_shot.py -- <输出json> [S11,S29...]

为什么要有它：0911 晚间用户说「光线很暗、建模离得太远看不清、浅色建模+浅色字体」。
这三件**看联络表都看不出来**——暗一点仍然「有东西」，小一点仍然「构图紧」，
撞色的字仍然「有字」。只有把帧渲出来按像素量才能排序修哪一镜。

每镜量 3 帧（25% / 55% / 85%），480×270，指标：
  fillh/fillw  主体（只算 MESH）占画面高 / 宽
  cshape       fillw/fillh。>1.0 就说明**内容比画幅还扁**（>1.9 是必须改布局的档），
               这时再怎么调相机主体也高不起来，必须改建模布局。
  clip         主体落在画内的比例（<0.98 = 出画）
  avg/p95/br   整帧平均亮度 / 95 分位 / 亮于中灰的像素占比
  subj         主体像素的平均亮度（把地板藏掉再渲一遍得到的蒙版）
  floorhot     地板是不是画面里最亮的东西（1 = 是，对比度塌了）
  txtmin       所有标签里「笔画 vs 背景」对比度最小的那个（<0.18 = 浅底浅字）
"""
import json, math, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bpy  # noqa: E402
import bl_lib as L  # noqa: E402
import bl_scene as bs  # noqa: E402

TMP = os.path.join(HERE, "work", "qcshot")
RES = (480, 270)
_cap = {}


def _shoot(sc, tag):
    """渲 3 帧到 TMP/tag_*，返回 [(帧号, numpy 灰度)]。"""
    import numpy as np
    out = []
    sc.render.resolution_x, sc.render.resolution_y = RES
    sc.render.resolution_percentage = 100
    sc.render.image_settings.file_format = "PNG"
    for i, t in enumerate((0.25, 0.55, 0.85)):
        f = max(1, min(_cap["N"], int(round(_cap["N"] * t))))
        sc.frame_set(f)
        sc.render.filepath = os.path.join(TMP, "%s_%d" % (tag, i))
        bpy.ops.render.render(write_still=True)
        p = sc.render.filepath + ".png"
        img = bpy.data.images.load(p)
        a = np.array(img.pixels[:], dtype=np.float32).reshape(RES[1], RES[0], 4)[::-1]
        bpy.data.images.remove(img)
        g = 0.2126 * a[..., 0] + 0.7152 * a[..., 1] + 0.0722 * a[..., 2]
        # ⛔ img.pixels 给的是**线性**值（PNG 标了 sRGB，Blender 读进来会转）。
        #    改版前那个「全片平均亮度 0.088」的基线是 PIL 直接读 PNG = **显示值**。
        #    两把尺子差一个 gamma，不转就会得出「改完更暗了」的假结论。这里统一转成显示值。
        g = np.clip(g, 0, 4)
        g = np.where(g <= 0.0031308, g * 12.92, 1.055 * np.power(np.maximum(g, 1e-8), 1 / 2.4) - 0.055)
        out.append((f, np.clip(g, 0, 1.2)))
    return out


def measure(name, fn):
    import numpy as np
    from bpy_extras.object_utils import world_to_camera_view
    from mathutils import Vector
    L._font = None                       # ⛔ read_factory_settings 之后字体模块缓存会失效
    os.makedirs(TMP, exist_ok=True)
    _cap["N"] = 240
    real_render = L.render

    def fake(sc, out_dir, start=None, end=None):
        _cap["N"] = end or 240
        _cap["sc"] = sc
    L.render = fake
    try:
        fn(os.path.join(TMP, "_"), False)
    finally:
        L.render = real_render
    sc = _cap.get("sc") or bpy.context.scene
    cam = sc.camera
    N = _cap["N"]

    # ---- 几何：取景 ----
    fh = fw = 0.0; clip = 1.0; cshape = 1.0
    for t in (0.25, 0.55, 0.85):
        sc.frame_set(max(1, min(N, int(round(N * t)))))
        bpy.context.view_layer.update()
        r = bs._content(sc, cam, kinds=("MESH",))
        if not r:
            continue
        x0, x1, y0, y1 = r[0]
        fh = max(fh, y1 - y0); fw = max(fw, x1 - x0)
        ins = (min(x1, 1) - max(x0, 0)) * (min(y1, 1) - max(y0, 0))
        tot = (x1 - x0) * (y1 - y0)
        clip = min(clip, ins / tot if tot > 0 else 1.0)
        if (y1 - y0) > 1e-6:
            cshape = max(cshape, (x1 - x0) / (y1 - y0))   # ⛔ 画面坐标里 x、y 各自已归一化，不能再除 16:9

    # ---- 标签的画面位置（后面在像素上量对比度） ----
    boxes = []
    sc.frame_set(max(1, int(N * 0.85))); bpy.context.view_layer.update()
    for ob in sc.objects:
        if ob.type != "FONT" or ob.hide_render or max(abs(v) for v in ob.scale) < 0.05:
            continue
        if ob.name.endswith("_hl"):        # 描边是字的副本，别重复统计
            continue
        try:
            nd = [world_to_camera_view(sc, cam, ob.matrix_world @ Vector(c)) for c in ob.bound_box]
        except Exception:
            continue
        if any(v.z <= 0 for v in nd):
            continue
        boxes.append((ob.name, min(v.x for v in nd), max(v.x for v in nd),
                      min(v.y for v in nd), max(v.y for v in nd)))

    # ---- 像素：全帧 + 藏掉地板的主体蒙版 ----
    shots = _shoot(sc, name)
    floors = [o for o in sc.objects if o.type == "MESH" and any(
        o.name.lower().startswith(s) for s in bs.FIT_SKIP)]
    for o in floors:
        o.hide_render = True
    nof = _shoot(sc, name + "_nf")
    for o in floors:
        o.hide_render = False

    avg = float(np.mean([g.mean() for _, g in shots]))
    p95 = float(np.mean([np.percentile(g, 95) for _, g in shots]))
    br = float(np.mean([(g > 0.5).mean() for _, g in shots]))
    subj = 0.0; floorhot = 0
    for (_, g), (_, gn) in zip(shots, nof):
        m = gn > 0.035                                  # 没地板时还亮着的就是主体
        subj += float(gn[m].mean()) if m.any() else 0.0
        if m.any() and float(g.max()) > float(gn[m].max()) * 1.08:
            floorhot += 1                               # 有地板时最亮值明显更高 = 地板抢了
    subj /= max(len(shots), 1)

    txtmin = 1.0
    _, g = shots[-1]
    H, W = g.shape
    for n, x0, x1, y0, y1 in boxes:
        i0 = int(max(0, (1 - y1) * H)); i1 = int(min(H, (1 - y0) * H))
        j0 = int(max(0, x0 * W)); j1 = int(min(W, x1 * W))
        if i1 - i0 < 3 or j1 - j0 < 3:
            continue
        patch = g[i0:i1, j0:j1].ravel()
        if patch.size < 12:
            continue
        stroke = float(np.percentile(patch, 88))        # 笔画
        back = float(np.percentile(patch, 35))          # 字缝里的背景
        txtmin = min(txtmin, abs(stroke - back))
    return dict(shot=name, fillh=round(fh, 3), fillw=round(fw, 3), cshape=round(cshape, 2),
                clip=round(clip, 3), avg=round(avg, 3), p95=round(p95, 3), br=round(br, 3),
                subj=round(subj, 3), floorhot=floorhot, nfont=len(boxes),
                txtmin=round(txtmin, 3) if boxes else None)


if __name__ == "__main__":
    a = sys.argv[sys.argv.index("--") + 1:]
    outp = a[0]
    import shotload
    S = shotload.load()
    print("镜头函数 %d 个" % len(S), flush=True)
    want = a[1].split(",") if len(a) > 1 and a[1] else sorted(S)
    rows = []
    for n in want:
        if n not in S:
            print("!! 没有这一镜", n, flush=True); continue
        try:
            r = measure(n, S[n])
        except Exception as e:
            r = dict(shot=n, err=str(e)[:120])
        rows.append(r)
        print(json.dumps(r, ensure_ascii=False), flush=True)
    json.dump(rows, open(outp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("QC_SHOT_OK %d" % len(rows), flush=True)
