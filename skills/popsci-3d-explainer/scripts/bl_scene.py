# -*- coding: utf-8 -*-
"""3D 场景框架 + 零件库。所有镜头都从这里搭，保证同一物体全片长得一样。

这个文件分两半：

  **上半＝通用框架（换题材不用动）**
    go()            一条龙：fit → relight → autoexpose → fix_text_pixels
    fit()           自动取景（只按 MESH 算）+ 标签排版四道工序 + 体检
    relight()       按内容包围球在相机坐标系里重新布光
    autoexpose()    渲小图量出来的曝光
    fix_text_pixels() 量「字将要落在的那块画面」有多亮，决定亮字还是深字
    reset_dark() / floor() / M() / opts()

  **下半＝零件库（**换题材就整个换掉这一段**）**
    m_pcb / m_chip / m_si …  材质
    dimm / chip / cell / wafer / stack / interposer / gpu_die / shelf …  半导体题材的零件
    保留它们是当**写法示例**：每个零件一个函数、返回可打关键帧的物体列表、
    尺寸用同一套单位、颜色只从下面这一套里取。

单位约定：1 blender 单位 ≈ 1 cm（这批零件里内存条长 13、芯片 1.1）。换题材时自己定一套并写在这儿。
配色和 cards.py 同一套：CYAN 主角、ORANGE 强调、GREY 配角，**只有主角发光**。
"""
import math, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bpy
import bl_lib as L
from bl_lib import CYAN, ORANGE, GOLD, RED, GREEN, WHITE, GREY

DARKBG = (0.009, 0.012, 0.019, 1)   # ⛔ 要和 floor() 的底色同量级，否则远处会出现一条明显亮过地板的地平线
NAVY = (0.03, 0.05, 0.09, 1)
_M = {}
_BASE = {}


def key_rel(o, f, mult):
    """按物体原始尺寸的倍数打 scale 关键帧。
    ⛔ L.box 把 size 存进 object.scale，所以对 box 直接 L.key_scale(o, f, (1,1,1)) 等于把它压成 1×1×1。"""
    if o.name not in _BASE:
        _BASE[o.name] = tuple(o.scale)
    b = _BASE[o.name]
    m = mult if isinstance(mult, (tuple, list)) else (mult, mult, mult)
    L.key_scale(o, f, (b[0] * m[0], b[1] * m[1], b[2] * m[2]))


FIT_SKIP = ("floor", "bg", "backdrop")

# 每镜可以关掉的自动动作。reset_dark() 会复位，所以只影响当前这一镜。
# 用法：镜头函数里写 bs.opts(oblique=False)，比如并排对比的镜头不能转，一转就把并排看成前后。
_OPT = {"oblique": True}


def opts(**kw):
    """oblique=False 关掉自动斜看；dim=(帧, 倍数, 过渡帧数) 到某一帧把全场灯调暗。"""
    _OPT.update(kw)


def _content(sc, cam, only_onscreen=True, kinds=("MESH", "FONT")):
    """当前帧「此刻的主体」在画面坐标里的外接框 + 世界中心 + 相机到它的距离。

    ⛔ 只算重心落在画内的物体。横移镜头（S64 井→行列→内存条）里还没走到的那一站
       本来就该在画外，把它也框进来会逼着相机退到什么都看不清。
    ⛔⛔ 0911 晚间：取景**只按 MESH 算**（kinds=("MESH",)）。上一版把标签也算进取景，
       一个标签飘出去就逼着相机退一大截，结果 51/84 镜主体只占画面高不到 60%，
       用户原话「为了完整展示导致建模离得太远了看不清楚」。标签改成自己挪进画面（_fit_labels）。
    """
    from bpy_extras.object_utils import world_to_camera_view
    from mathutils import Vector
    keep = []
    for ob in sc.objects:
        try:
            if ob.hide_render or ob.type not in kinds:
                continue
            if any(ob.name.lower().startswith(s) for s in FIT_SKIP):
                continue
            mw = ob.matrix_world
            pts = [mw @ Vector(c) for c in ob.bound_box]
            nd = [world_to_camera_view(sc, cam, p) for p in pts]
            if any(v.z <= 0 for v in nd):        # 在相机背后，不参与取景
                continue
            if max(abs(p.x) for p in pts) > 1e4:
                continue
        except Exception:
            continue
        cx = sum(v.x for v in nd) / 8.0; cy = sum(v.y for v in nd) / 8.0
        # 文字是自己写上去的，任何时候都得在画内；否则「重心出画就不算」会变成
        # 「标签跑出去了反而没人管」——S30/S43 就是这么漏的。
        on = (ob.type == "FONT" and not os.environ.get("BL_FIT_OLD")) or (-0.05 <= cx <= 1.05 and -0.05 <= cy <= 1.05)
        keep.append((on, nd, pts))
    on = [k for k in keep if k[0]]
    use = on if (only_onscreen and on) else keep
    xs = [v.x for _, nd, _ in use for v in nd]
    ys = [v.y for _, nd, _ in use for v in nd]
    wp = [p for _, _, pts in use for p in pts]
    if not xs:
        return None
    c = Vector((sum(p.x for p in wp) / len(wp), sum(p.y for p in wp) / len(wp), sum(p.z for p in wp) / len(wp)))
    return (min(xs), max(xs), min(ys), max(ys)), c, (c - cam.matrix_world.translation).length


def _k(box, margin):
    """要把这一帧拍全，画面得放大到几分之一（>1 表示超框，需要往后退）。"""
    x0, x1, y0, y1 = box
    m = 0.5 - margin
    return max(abs(x0 - 0.5), abs(x1 - 0.5), abs(y0 - 0.5), abs(y1 - 0.5)) / m


def _loc_frames(cam):
    ad = cam.animation_data
    if not ad or not ad.action:
        return []
    fs = set()
    for fc in ad.action.fcurves:
        if fc.data_path == "location":
            for kp in fc.keyframe_points:
                fs.add(int(round(kp.co[0])))
    return sorted(fs)


MIN_TXT = 0.026          # 3D 标签在画面上的最小高度（1080p 约 28 px，再小就读不出来）
SUB_TOP = 0.225          # 字幕带上沿（MarginV 120 + 60 号字，约画面底部 22%）
# ⛔ 排标签的四道工序（收进画面 / 让开字幕 / 推开重叠 / 体检）必须看**同一组帧**。
#    各看各的，体检就会在别人没看过的那一帧上报错，而且永远修不掉。
LPROBE = (0.15, 0.3, 0.45, 0.6, 0.75, 0.9, 0.99)


def _nbox(sc, cam, ob):
    """标签在画面上的框 (x0, x1, y0, y1)；看不见就返回 None。

    ⛔⛔ 一律按**满尺寸**量，不按当前缩放。标签是 `pop()` 弹出来的，弹出那几帧
       scale 还在 0.3、0.7，量出来的框比真身小一圈——按小框推开，等它长到满尺寸又压上了
       （S82 的「九月初松了一点」和「但晶圆厂满产」死活分不开就是这个）。
    """
    from bpy_extras.object_utils import world_to_camera_view
    from mathutils import Vector, Matrix
    try:
        if ob.hide_render or ob.type != "FONT" or max(abs(v) for v in ob.scale) < 0.05:
            return None
        loc, rot, _ = ob.matrix_world.decompose()
        mw = Matrix.LocRotScale(loc, rot, Vector((1.0, 1.0, 1.0)))
        nd = [world_to_camera_view(sc, cam, mw @ Vector(c)) for c in ob.bound_box]
    except Exception:
        return None
    if any(v.z <= 0 for v in nd):
        return None
    return (min(v.x for v in nd), max(v.x for v in nd),
            min(v.y for v in nd), max(v.y for v in nd))


def _lift_labels(sc, cam, N, tries=6):
    """把落进字幕带的 3D 标签往上抬，直到让开字幕。

    ⛔ 0911：84 镜里 25 镜的标签和字幕叠在一起（S58 的「每 G 8 美元」直接压在字幕上）。
       画面底部那一条是字幕的地盘，3D 标签不许进去。
    """
    import bpy as _b
    from bpy_extras.object_utils import world_to_camera_view
    from mathutils import Vector
    probe = [max(1, min(N, int(round(N * t)))) for t in LPROBE]
    moved = 0
    for _ in range(tries):
        need = {}
        for f in probe:
            sc.frame_set(f); _b.context.view_layer.update()
            up = cam.matrix_world.to_quaternion() @ Vector((0, 1, 0))
            for ob in sc.objects:
                bx = _nbox(sc, cam, ob)
                if bx is None:
                    continue
                x0, x1, y0, y1 = bx
                mw = ob.matrix_world
                # ⛔⛔ 别拿「已经掉到画面外了」当放过的理由。旧判据 y1<=0.04 / x 在两侧
                #    就跳过，结果 S84 的「英特尔卖出第一颗商用 DRAM」贴着画面最底下那一条、
                #    「一颗上面 1024 个格子」整条掉出画外——**一个字都看不见，还不报错**。
                #    规矩只有一条：字幕带上沿以下不许有 3D 标签，在画外的更要捞回来。
                if y0 >= SUB_TOP:
                    continue
                d = (mw.translation - cam.matrix_world.translation).length
                # ⛔ 传感器是 AUTO 适配，竖直视角要从 sensor_width × 画幅比例算，别用 sensor_height（默认 24 是错的）
                fh = d * cam.data.sensor_width / cam.data.lens * (sc.render.resolution_y / sc.render.resolution_x)
                # ⛔ 沿世界 Z 抬对俯拍镜头无效（那时画面的「上」几乎是世界 -Y）。
                #    一律沿相机的画面向上方向移，任何机位都成立。
                # ⛔ 换算成世界位移要用**这一帧**的相机基向量。镜头在推/摇的时候，
                #    拿第一帧的「上」去挪，到这一帧根本不是往上。
                v = up * ((SUB_TOP + 0.02 - y0) * fh)
                p = need.get(ob.name)
                if p is None or v.length > p.length:
                    need[ob.name] = v
        if not need:
            break
        for n, v in need.items():
            sc.objects[n].location = sc.objects[n].location + v; moved += 1
    sc.frame_set(1)
    return moved


def _unocclude(sc, cam, N, tries=3):
    """让标签从遮挡物后面出来。

    ⛔ 0911：84 镜里 18 镜的标签被挡住，大头是**被地板埋了**——标签放在 z 负值、
       地板面在它上面，渲出来一个字看不见（S46 的「倒了」、S70 的四个路标名全中）。
    两步：① 低于地板面的直接抬到地板上方；② 还被别的东西挡的，沿相机视线挪到遮挡物前面
    （在同一条射线上，屏幕位置不变），再按距离比例把字号补回来。
    """
    import bpy as _b
    from mathutils import Vector
    ftop = None
    for ob in sc.objects:
        if ob.type == "MESH" and ob.name.lower().startswith("floor"):
            ftop = max(ftop if ftop is not None else -1e9, max((ob.matrix_world @ Vector(c)).z for c in ob.bound_box))
    fixed = 0
    if ftop is not None:
        for ob in sc.objects:
            if ob.type == "FONT" and ob.parent is None and ob.location.z < ftop + 0.25:
                ob.location.z = ftop + 0.35; fixed += 1
    probe = [max(1, min(N, int(round(N * t)))) for t in (0.35, 0.7, 0.95)]
    for _ in range(tries):
        moved = 0
        for f in probe:
            sc.frame_set(f); _b.context.view_layer.update()
            dg = _b.context.evaluated_depsgraph_get()
            o = cam.matrix_world.translation
            for ob in list(sc.objects):
                if ob.type != "FONT" or ob.parent is not None or ob.hide_render:
                    continue
                if max(abs(v) for v in ob.scale) < 0.05:
                    continue
                v = ob.matrix_world.translation - o
                d = v.length
                if d < 0.5:
                    continue
                v = v.normalized()
                hit, loc, _, _, obj, _ = sc.ray_cast(dg, o + v * 0.05, v)
                if not (hit and obj and obj.name != ob.name):
                    continue
                hd = (loc - o).length
                if hd > d - 0.25:
                    continue
                nd = max(d * 0.55, hd - 0.35)          # 最多往前挪四成距离，别贴到镜头上
                ob.location = o + v * nd
                ob.data.size *= nd / d                  # ⛔ 补字号要改 data.size：object.scale 上有 pop 的关键帧
                moved += 1; fixed += 1
        if not moved:
            break
    sc.frame_set(1)
    return fixed


def _spread_labels(sc, cam, N, gap=0.018, tries=4):
    """同一帧里互相压着的标签，沿画面纵向推开。

    ⛔ 加了「最小在屏高度」之后，原来擦肩而过的标签会开始互相重叠
       （S24 的「4070 Ti」和「一秒 40 万亿次计算」叠成一团）。
    做法：按画面纵向从上到下排，谁压到上面那个就往下推，推的量换算回世界坐标沿相机的 up 走。
    """
    import bpy as _b
    from bpy_extras.object_utils import world_to_camera_view
    from mathutils import Vector
    # ⛔ 标签是按拍点一条条冒出来的，两条叠不叠只有在**两条都在画面上的那段**才看得出来。
    #    采三帧会漏掉最后冒出来的那条（S84 的「一颗上面 1024 个格子」在 0.70 才出现）。
    probe = [max(1, min(N, int(round(N * t)))) for t in LPROBE]
    moved = 0
    for _ in range(tries):
        need = {}
        for f in probe:
            sc.frame_set(f); _b.context.view_layer.update()
            q = cam.matrix_world.to_quaternion(); up = q @ Vector((0, 1, 0))
            box = []
            for ob in sc.objects:
                if ob.name.endswith("_hl"):
                    continue
                bx = _nbox(sc, cam, ob)
                if bx is None:
                    continue
                box.append([ob, bx[0], bx[1], bx[2], bx[3]])
            # ⛔ 默认**往上**推：往下推会和 _lift_labels（把标签顶出字幕带）互相抵消，
            #    S58 两条标签就是这么一个往下一个往上、最后原地重叠的。
            # ⛔ 但上面顶到头就必须让下面那条往下让——S58 的「每 G 8 美元 · DDR5 的五六倍」
            #    上沿已经到 0.954（画框是 0.955），再往上推等于没推，两条永远压着。
            #    往下让的底线是字幕带上沿，让不动就各让一半，至少把重叠减到最小。
            def _fh(o):
                dist = (o.matrix_world.translation - cam.matrix_world.translation).length
                return dist * cam.data.sensor_width / cam.data.lens * (sc.render.resolution_y / sc.render.resolution_x)

            def _acc(nm, dz):
                # ⛔ 用**这一帧**的相机「上」方向换算（镜头在推的时候第一帧的基向量不作数）
                v = up * dz
                o = need.get(nm)
                if o is None or v.length > o.length:
                    need[nm] = v

            box.sort(key=lambda b: b[3])           # 从画面下方往上排
            for i in range(1, len(box)):
                for j in range(i):
                    ob, x0, x1, y0, y1 = box[i]
                    lo, a0, a1, b0, b1 = box[j]
                    if x1 < a0 - 0.01 or x0 > a1 + 0.01:      # 横向不重叠就不管
                        continue
                    if y0 >= b1 + gap:
                        continue
                    d = (b1 + gap) - y0
                    du = min(d, max(0.0, 0.95 - y1))          # 上面还剩多少地方
                    dd = min(d - du, max(0.0, b0 - SUB_TOP))  # 不够就让下面那条往下让
                    if du:
                        box[i][3] += du; box[i][4] += du
                        _acc(ob.name, du * _fh(ob))
                    if dd:
                        box[j][3] -= dd; box[j][4] -= dd
                        _acc(lo.name, -dd * _fh(lo))
                    if not du and not dd:      # 上面顶到画框、下面顶到字幕带，只能改布局
                        print("  LABEL_STUCK f%d %s(y%.2f-%.2f)×%s(y%.2f-%.2f)"
                              % (f, ob.name, y0, y1, lo.name, b0, b1), flush=True)
        if not need:
            break
        for n, v in need.items():
            sc.objects[n].location = sc.objects[n].location + v; moved += 1
    sc.frame_set(1)
    return moved


def _label_audit(sc, cam, N):
    """排完之后自己查一遍，把没排干净的打进渲染日志。

    ⛔ 标签摞成一团、掉出画外都不报错，联络表缩到 1/6 大小也看不出来——
       S84 三条标签摞成一行乱码，是靠 1080p 原图才发现的。这里逐帧量一遍，
       log 里 grep 一下 LABEL_BAD 就知道还有哪几镜要手改布局。
    """
    import bpy as _b
    from bpy_extras.object_utils import world_to_camera_view
    from mathutils import Vector
    bad = []
    for t in LPROBE:
        f = max(1, min(N, int(round(N * t))))
        sc.frame_set(f); _b.context.view_layer.update()
        box = []
        for ob in sc.objects:
            if ob.name.endswith("_hl"):
                continue
            bx = _nbox(sc, cam, ob)
            if bx is None:
                continue
            box.append((ob.name, bx[0], bx[1], bx[2], bx[3]))
        for n, x0, x1, y0, y1 in box:
            if y0 < SUB_TOP - 0.005 or y1 > 1.0 or x0 < 0 or x1 > 1.0:
                bad.append("f%d %s 出界 x[%.2f %.2f] y[%.2f %.2f]" % (f, n, x0, x1, y0, y1))
        for i in range(len(box)):
            for j in range(i + 1, len(box)):
                a, b = box[i], box[j]
                if a[2] < b[1] or a[1] > b[2] or a[4] < b[3] or a[3] > b[4]:
                    continue
                bad.append("f%d %s×%s 相压" % (f, a[0], b[0]))
    for s in bad[:6]:
        print("  LABEL_BAD %s" % s, flush=True)
    return len(bad)


def _fit_labels(sc, cam, N, margin=0.045, tries=4, resize=True):
    """标签自己挪进画面，**不许把相机顶出去**。

    ⛔⛔ 0911 晚间用户第 3 条：上一版把标签也算进取景，一个标签飘出去就逼相机后退一大截，
       结果主体只占画面高中位 55%。现在取景只认建模，标签出框就沿画面横纵方向平移回来，
       实在太大就缩字号（改 data.size，⛔ 不能动 object.scale，那上面有 pop 的关键帧）。
    """
    import bpy as _b
    from bpy_extras.object_utils import world_to_camera_view
    from mathutils import Vector
    probe = [max(1, min(N, int(round(N * t)))) for t in LPROBE]
    moved = 0
    for _ in range(tries):
        shift = {}; cap = {}; want = {}
        for f in probe:
            sc.frame_set(f); _b.context.view_layer.update()
            q = cam.matrix_world.to_quaternion()
            right = q @ Vector((1, 0, 0)); up = q @ Vector((0, 1, 0))
            for ob in sc.objects:
                bx = _nbox(sc, cam, ob)
                if bx is None:
                    continue
                x0, x1, y0, y1 = bx
                d = (ob.matrix_world.translation - cam.matrix_world.translation).length
                fw = d * cam.data.sensor_width / cam.data.lens
                fh = fw * (sc.render.resolution_y / sc.render.resolution_x)
                # ⛔⛔ 「缩小」和「放大」不能共用一个字典。镜头会推近：同一条标签在 t=0.5 那帧
                #    还不到 2.6% 高（按规矩要放大 2.4 倍），到 t=0.9 已经横跨整幅画。旧代码
                #    一个 min 一个 max 往同一个 key 上写、还各自 continue，最后哪一帧写的算哪一帧，
                #    S33 的「地基：专管调度的那一颗」就这么被放成了 120% 画幅宽的一条横幅。
                #    正确做法：分开收——cap 是「全程都塞得进画面」的上限（取各帧最小），
                #    want 是「最小的那一帧也读得出来」的下限，最后 want 先取、再被 cap 压住。
                sx = (1 - 2 * margin) / max(x1 - x0, 1e-6)
                sy = (1 - 2 * margin - SUB_TOP) / max(y1 - y0, 1e-6)
                if resize:
                    cap[ob.name] = min(cap.get(ob.name, 9.9), min(sx, sy))
                    # 字号写死在世界坐标里，而相机距离是解出来的：同一个 size=0.5 在 26 单位外
                    # 只有十来像素（S14 的「只有十厘米粗」糊成一条）。低于画面高 2.6% 就放大。
                    if (y1 - y0) < MIN_TXT and (x1 - x0) < 0.62:
                        want[ob.name] = max(want.get(ob.name, 1.0), min(MIN_TXT / max(y1 - y0, 1e-6), 2.4))
                dx = dy = 0.0
                if x0 < margin:
                    dx = (margin - x0) * fw
                elif x1 > 1 - margin:
                    dx = -(x1 - (1 - margin)) * fw
                if y1 > 1 - margin:
                    dy = -(y1 - (1 - margin)) * fh
                if dx or dy:
                    # ⛔ 几帧的位移不能相加：同一条标签在两帧各差 0.1、0.08，加起来推 0.18
                    #    就推过头，下一轮再往回推——四轮打转谁都没修好。取**需求最大的那一帧**，
                    #    而且要用那一帧的相机基向量算（镜头在摇的时候，用第一帧的基向量换算出来的
                    #    世界位移，到第 0.75 帧根本不是那个方向——S68 的标签就这么一直差 2% 挂在画外）。
                    v = right * dx + up * dy
                    p = shift.get(ob.name)
                    if p is None or v.length > p.length:
                        shift[ob.name] = v
        did = 0
        for n in set(cap) | set(want):
            k = max(1.0, want.get(n, 1.0))        # 想放大到读得出来
            k = min(k, cap.get(n, 9.9))           # 但全程都必须塞得进画面，这条优先
            k = max(0.45, min(k, 2.4))
            if abs(k - 1.0) > 0.015:
                sc.objects[n].data.size *= k; moved += 1; did += 1
        for n, v in shift.items():
            sc.objects[n].location = sc.objects[n].location + v; moved += 1
        if not did and not shift:
            break
    sc.frame_set(1)
    return moved


AIM_Y = 0.57             # 内容重心该落在画面高度的哪儿（略高于正中，把底部 22% 让给字幕）


def _reaim(sc, cam, N, tol=0.012):
    """把相机重新对准内容重心。

    ⛔⛔ 0911 晚：只改距离是不够的。S29 里内存条和叠楼一左一右、重心偏在画面 42% 处，
       相机却对着原来手写的 target，于是「把两样都拍全」只能靠退远——主体就小了。
       这里逐个 location 关键帧算出内容重心在画面里偏了多少，换算成角度改写 rotation 关键帧。
       相机的机位一动不动，只转头，所以运镜轨迹（orbit / push）全部保持原样。
    """
    import bpy as _b
    from mathutils import Vector, Quaternion
    frames = _loc_frames(cam)
    if len(frames) < 5:
        # ⛔ 只在首尾两个关键帧上对准是不够的：中间是插值出来的，主体会在半程飘到一边
        #    （S11 在 t=0.25 时整个跑到画面右半边）。补几个中间点，只插旋转关键帧。
        frames = sorted(set(frames) | {max(1, min(N, int(round(1 + (N - 1) * t)))) for t in (0, .2, .4, .6, .8, 1)})
    ad = cam.animation_data
    has_rot = bool(ad and ad.action and any(fc.data_path == "rotation_euler" for fc in ad.action.fcurves))
    prev = None
    moved = 0.0
    LIMIT = math.radians(22)     # ⛔ 总转角封顶：符号写反过一次，相机一路转到只剩地板棱
    for f in frames:
        keep = cam.rotation_euler.copy()
        spent = 0.0
        for _ in range(4):
            sc.frame_set(f); _b.context.view_layer.update()
            r = _content(sc, cam, kinds=("MESH",))
            if not r:
                cam.rotation_euler = keep          # 转丢了就退回原朝向，绝不硬转
                break
            (x0, x1, y0, y1) = r[0]
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            dx, dy = cx - 0.5, cy - AIM_Y
            if abs(dx) < tol and abs(dy) < tol:
                break
            q = cam.matrix_world.to_quaternion()
            right = q @ Vector((1, 0, 0)); up = q @ Vector((0, 1, 0))
            fw = cam.data.sensor_width / cam.data.lens
            fh = fw * (sc.render.resolution_y / sc.render.resolution_x)
            # ⛔ 符号：绕相机 up 轴**正向**旋转会把镜头转向左边，所以内容偏右（dx>0）要用负角；
            #    绕 right 轴正向旋转是抬头，内容偏高（dy>0）就用正角。写反了画面会发散。
            yaw = -math.atan(dx * fw)
            pit = math.atan(dy * fh)
            spent += abs(yaw) + abs(pit)
            if spent > LIMIT:
                cam.rotation_euler = keep
                break
            q = (Quaternion(up, yaw) @ Quaternion(right, pit)) @ q
            cam.rotation_euler = q.to_euler("XYZ", prev) if prev else q.to_euler("XYZ")
            # ⛔⛔ 必须**当场**打关键帧。相机的旋转是 orbit/key_cam 烤出来的曲线，
            #    下一轮 sc.frame_set(f) 会按曲线把 rotation_euler 重新求值，
            #    不先落成关键帧的话这一步修正立刻被冲掉——调了半天画面纹丝不动就是这个原因。
            cam.keyframe_insert("rotation_euler", frame=f)
            moved += abs(yaw) + abs(pit)
        prev = cam.rotation_euler.copy()
        cam.keyframe_insert("rotation_euler", frame=f)
    sc.frame_set(1)
    return moved


def _oblique(sc, cam, N, ratio=1.9, turns=(0, -20, 20, -35, 35, -50, 50)):
    """内容比画幅扁太多时，把相机**绕内容中心转到斜着看长轴**，用透视把宽度压回来。

    ⛔ 这是「主体太小」剩下的那一半原因。取景只能改距离和朝向，改不了内容自身的宽高比：
       一根内存条是 13×3，四个路标横着排是 27×5，正面拍无论怎么调，主体占画面高都上不去。
       斜着看同一条线，投影宽度按 cos 压缩，主体立刻就高了——而且纵深感本身更好看。
    做法是**实测**：把所有相机关键帧绕内容中心的竖轴转几个角度，量哪个角度的
    「画面宽/画面高」最接近 1，就用哪个。转完由外层 fit 重新解距离。
    """
    import bpy as _b
    from mathutils import Vector, Matrix
    frames = _loc_frames(cam) or [1]
    probe = [max(1, min(N, int(round(N * t)))) for t in (0.25, 0.55, 0.85)]

    def measure():
        rs = []
        for f in probe:
            sc.frame_set(f); _b.context.view_layer.update()
            r = _content(sc, cam, kinds=("MESH",))
            if r:
                x0, x1, y0, y1 = r[0]
                if y1 - y0 > 1e-4:
                    rs.append((x1 - x0) / (y1 - y0))
        return max(rs) if rs else 1.0

    if measure() <= ratio:
        sc.frame_set(1); return 0
    sc.frame_set(probe[1]); _b.context.view_layer.update()
    r = _content(sc, cam, kinds=("MESH",))
    if not r:
        sc.frame_set(1); return 0
    c = r[1]
    base = {f: None for f in frames}
    for f in frames:
        sc.frame_set(f); _b.context.view_layer.update()
        base[f] = (cam.matrix_world.translation.copy(), cam.rotation_euler.copy())
    best = (measure(), 0)
    for deg in turns[1:]:
        M = Matrix.Rotation(math.radians(deg), 4, "Z")
        for f in frames:
            loc, rot = base[f]
            cam.location = c + (M @ (loc - c))
            cam.rotation_euler = (M.to_3x3() @ rot.to_matrix()).to_euler("XYZ", rot)
            cam.keyframe_insert("location", frame=f)
            cam.keyframe_insert("rotation_euler", frame=f)
        m = measure()
        if m < best[0] - 0.05:
            best = (m, deg)
    M = Matrix.Rotation(math.radians(best[1]), 4, "Z")
    for f in frames:
        loc, rot = base[f]
        cam.location = c + (M @ (loc - c))
        cam.rotation_euler = (M.to_3x3() @ rot.to_matrix()).to_euler("XYZ", rot)
        cam.keyframe_insert("location", frame=f)
        cam.keyframe_insert("rotation_euler", frame=f)
    sc.frame_set(1)
    return best[1]


def fit(sc, cam, N, margin=0.055, tries=5, pct=0.86, target=0.0):
    """渲染前自动补取景：解出相机该在多远，**推近和后退都做**。

    ⛔ 0911 早：68 镜里 59 镜建模超框（最惨的只看得见 5%），所以加了自动后退。
    ⛔⛔ 0911 晚：用户「为了完整展示导致建模离得太远了看不清楚，视觉效果要震撼」。
       上一版只在 k>1.015（超框）时才动相机，从不推近，而且把标签算进取景，
       两条加起来让主体只占画面高中位 55%、51/84 镜不到 60%。
    新做法两条：
      ① 取景**只认 MESH**，标签交给 _fit_labels 自己挪回来；
      ② 每轮都把 k 解到 1.0 附近——k<1 说明还有富余，相机就往前推，把主体顶满画面。
    单帧飞入飞出不算数（取 86 分位），地板类不参与。相机朝向一个字不动，只改距离。
    """
    import bpy as _b
    from mathutils import Vector
    frames = _loc_frames(cam)
    probe = [max(1, min(N, int(round(N * t)))) for t in (0.06, 0.2, 0.35, 0.5, 0.65, 0.8, 0.96)]
    MESH = ("MESH",)

    def solve(kmin, kmax):
        """量一轮，返回该乘的距离系数（>1 后退，<1 推近）。"""
        ks = []
        for f in probe:
            sc.frame_set(f); _b.context.view_layer.update()
            r = _content(sc, cam, kinds=MESH)
            if r:
                ks.append(_k(r[0], margin))
        if not ks:
            return None
        ks.sort()
        k = ks[min(len(ks) - 1, int(len(ks) * pct))]
        return max(kmin, min(kmax, k))

    def move(k):
        tgt = {}
        for f in (frames or [1]):
            sc.frame_set(f); _b.context.view_layer.update()
            r = _content(sc, cam, kinds=MESH)
            d = r[2] if r else 10.0
            fwd = cam.matrix_world.to_quaternion() @ Vector((0, 0, -1))
            tgt[f] = cam.matrix_world.translation - fwd * (d * (k - 1))
        for f, loc in tgt.items():
            cam.location = loc
            if frames:
                cam.keyframe_insert("location", frame=f)

    # 0911 晚用户「视觉效果要震撼」：把镜头适度放宽，fit 随后会把相机推近，
    # 同样的取景换来更强的透视和体积感。俯拍不动（广角俯拍会把方阵拉成梯形）。
    if not os.environ.get("BL_NO_WIDE"):
        import bpy as _bb
        fwd_z = (cam.matrix_world.to_quaternion() @ __import__("mathutils").Vector((0, 0, -1))).z
        if cam.data.lens > 36 and fwd_z > -0.75:
            cam.data.lens = max(32.0, cam.data.lens * 0.80)
    # ⛔⛔ 总退量封顶。S18 这类「一路推到极近看细节」的镜头，末段本来就该只剩局部；
    #     不封顶的话 fit 以为出画了、一路退到 ×13.8，主体缩成画面中间一个小方块。
    #     真出画的由 qc_shot 的 clip 报出来逐镜改，不能靠无限后退兜底。
    CAP = 2.5
    deg = _oblique(sc, cam, N) if _OPT.get("oblique", True) else 0
    moved = 1.0
    for _ in range(tries):
        _reaim(sc, cam, N)                    # 先转头对准重心，再谈距离——不然只能靠退远把偏心的内容框进来
        k = solve(0.55, 1.8)                  # ⛔ 下限 0.55：一轮最多推近四成半，别一步怼到脸上
        if k is None or abs(k - 1.0) <= 0.02:
            break
        k = min(k, max(1.0, CAP / moved))
        if k <= 1.001:
            break
        move(k); moved *= k
    if not os.environ.get("BL_FIT_OLD"):
        _fit_labels(sc, cam, N)               # 标签先挪进画面
        _lift_labels(sc, cam, N)              # 再让开字幕带
        if not os.environ.get("BL_NO_UNOCC"):
            _unocclude(sc, cam, N)            # 从遮挡物后面挪出来
    for _ in range(2):                        # 建模的取景再确认一遍
        k = solve(0.8, 1.6)
        if k is None or abs(k - 1.0) <= 0.02:
            break
        k = min(k, max(1.0, CAP / moved))     # 同样受总退量封顶
        if k <= 1.001:
            break
        move(k); moved *= k
    if not os.environ.get("BL_FIT_OLD"):
        # ⛔⛔ 推开重叠必须是**最后一件事**，而且要在相机彻底定死之后。
        #    病因有两层：① `_lift_labels` 把每条掉进字幕带的标签下沿都顶到同一个 y，
        #       两条就正好摞成一条（S84 的「1970 年 10 月」和「英特尔卖出第一颗商用 DRAM」
        #       渲出来是糊成一团的乱码）；② 推开之后只要相机再动一次或者字号再改一次，
        #       屏幕位置全变，刚推开的又叠回去。
        #    所以：相机定死 → 允许改字号收一次 → 之后只推不改号，循环到不动为止。
        #    ⛔ 让开字幕带也得留在这个循环里：相机一推近，原来让开了的标签会重新掉回底部
        #       （第一版修完 S84 的青字直接落到画面最底下那一条）。两件都是**往上推**，
        #       不像上一版「一个往下一个往上」那样互相抵消，可以放心同循环。
        _fit_labels(sc, cam, N)
        # ⛔ 循环里三件事的顺序要让「推开重叠」落在最后一件：收回画面（_fit）会把刚推开的
        #    又推回去，谁在最后谁说了算。三件都不动了才算收敛。
        for _ in range(6):
            n = _fit_labels(sc, cam, N, resize=False)    # 只平移，改字号会把框改了又叠上
            n += _lift_labels(sc, cam, N)
            n += _spread_labels(sc, cam, N)
            if not n:
                break
        _label_audit(sc, cam, N)
    if deg:
        print("  斜看长轴 %+d°" % deg, flush=True)
    if cam.data.dof.use_dof:                  # 距离变了焦点要跟着走，否则主角全虚
        sc.frame_set(probe[len(probe) // 2]); _b.context.view_layer.update()
        r = _content(sc, cam, kinds=MESH)
        if r:
            cam.data.dof.focus_distance = max(0.5, r[2])
    sc.frame_set(1)
    return moved


# ---------- 布光（0911 晚间用户第 3 条：光线很暗，建模照不全） ----------
# 灯的能量必须跟距离平方走。旧版把灯写死在 (4,-5,6)、能量写死几百瓦，
# 而 fit() 会把相机退到任意远、场景尺度从 13（内存条）到 400（井阵）差三十倍，
# 于是近的过曝、远的全黑：全片抽 125 帧实测平均亮度中位只有 0.088，
# 亮于中灰的像素只占 2.9%。改成按内容包围球半径 R 布光、能量 ∝ d²，
# 并且灯的方位跟着**相机**转，保证永远照在看得见的那一面上。
# ⛔ 补光和顶光不能省。用户要的是「所有建模都被完整照亮」，主光独大会让背光那一半整个沉下去
#    （S06 的货架就几乎看不见）。补光提到主光的 2/3、顶光提到一半，灯面也放大——软光才铺得开。
KEY_E, FILL_E, RIM_E, TOP_E = 23.0, 15.0, 15.0, 12.0


def relight(sc, cam, N, key=1.0, fill=1.0, rim=1.0, top=1.0, warm=True):
    """按内容尺度重新布光。必须在 fit() 之后调用（要用最终的相机位置）。"""
    import bpy as _b
    from mathutils import Vector
    for ob in [o for o in sc.objects if o.type == "LIGHT"]:
        _b.data.objects.remove(ob, do_unlink=True)
    probe = [max(1, min(N, int(round(N * t)))) for t in (0.15, 0.4, 0.65, 0.9)]
    pts = []
    for f in probe:
        sc.frame_set(f); _b.context.view_layer.update()
        r = _content(sc, cam, kinds=("MESH",))
        if r:
            pts.append(r[1])
    if not pts:
        sc.frame_set(1); return None
    c = Vector((sum(p.x for p in pts) / len(pts), sum(p.y for p in pts) / len(pts), sum(p.z for p in pts) / len(pts)))
    sc.frame_set(probe[len(probe) // 2]); _b.context.view_layer.update()
    r = _content(sc, cam, kinds=("MESH",))
    R = max(2.0, r[2] * 0.42) if r else 10.0          # 用相机距离反推内容尺度，稳过量包围盒
    q = cam.matrix_world.to_quaternion()
    fwd = q @ Vector((0, 0, -1)); right = q @ Vector((1, 0, 0)); up = q @ Vector((0, 1, 0))

    def add(dirv, dist, energy, size, color):
        d = dirv.normalized()
        _b.ops.object.light_add(type="AREA", location=c + d * dist)
        o = _b.context.object
        o.data.energy = energy * dist * dist
        o.data.size = size; o.data.color = color
        o.data.shape = "DISK"
        L.look(o, tuple(c))
        return o

    w = (1.0, 0.95, 0.90) if warm else (1, 1, 1)
    # ⛔ 主光压得太平，它在地板上的镜像会变成一大团白光斑、比主体还亮（S70/S80 都中招）。
    #    抬到接近顶光，镜像就缩到主体脚下那一小块。
    k = add(-fwd * 0.30 + right * 0.55 + up * 1.15, R * 2.6, KEY_E * key, R * 1.20, w)
    f = add(-fwd * 0.85 - right * 0.78 + up * 0.18, R * 2.8, FILL_E * fill, R * 2.10, (0.70, 0.84, 1.0))
    m = add(fwd * 0.80 + up * 0.45 - right * 0.25, R * 2.4, RIM_E * rim, R * 0.95, (0.48, 0.78, 1.0))
    t = add(up * 1.0 - fwd * 0.25, R * 3.0, TOP_E * top, R * 2.8, (0.86, 0.92, 1.0))
    sc.frame_set(1)
    return k, f, m, t


def _lum(c):
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def _mat_lum(ob):
    """这个物体在画面上大概有多亮（0~1）。发光材质按发光算，普通材质按底色 × 打光系数。"""
    try:
        m = ob.data.materials[0]
        n = m.node_tree.nodes.get("Principled BSDF") or next(
            (x for x in m.node_tree.nodes if x.type == "BSDF_PRINCIPLED"), None)
        if n is None:
            return 0.25
        base = _lum(n.inputs["Base Color"].default_value)
        try:
            e = n.inputs["Emission Color"].default_value
            s = float(n.inputs["Emission Strength"].default_value)
        except KeyError:
            e, s = (0, 0, 0, 1), 0.0
        if s > 0.4:
            return min(1.0, _lum(e) * min(s / 2.2, 1.6))
        return min(1.0, base * 0.72)
    except Exception:
        return 0.25


DARK_TXT = (0.010, 0.016, 0.026, 1)
# ⛔ autoexpose 会把全场的灯和发光一起缩放。之后再新建的材质（字色纠正、描边）
#    不在那次缩放里，直接写 emit_str=3.0 会比全场亮十倍。一律乘这个系数。
_EXPO = {"k": 1.0}


def _own_color(ob):
    """标签自己的颜色（优先发光色，其次底色）。换深/提亮时保留色相，不要一律变白。"""
    try:
        m = ob.data.materials[0]
        n = next(x for x in m.node_tree.nodes if x.type == "BSDF_PRINCIPLED")
        try:
            e = n.inputs["Emission Color"].default_value
            if _lum(e) > 0.02 and float(n.inputs["Emission Strength"].default_value) > 0.1:
                return tuple(e)
        except KeyError:
            pass
        return tuple(n.inputs["Base Color"].default_value)
    except Exception:
        return WHITE


def _stretch_floor(sc, cam, N):
    """地板撑到画外去。⛔ 相机退远/推近以后，原来写死的 floor(-0.3, 160) 边缘会露在画面里，
    远处出现一条突兀的横线。按相机距离把地板拉大。"""
    import bpy as _b
    from mathutils import Vector
    sc.frame_set(max(1, int(N * 0.5))); _b.context.view_layer.update()
    r = _content(sc, cam, kinds=("MESH",))
    d = r[2] if r else 20.0
    for ob in sc.objects:
        if ob.type != "MESH" or not any(ob.name.lower().startswith(s) for s in FIT_SKIP):
            continue
        bb = [ob.matrix_world @ Vector(c) for c in ob.bound_box]
        w = max(p.x for p in bb) - min(p.x for p in bb)
        need = d * 9.0
        if w < need and w > 1e-6:
            k = need / w
            ob.scale = (ob.scale[0] * k, ob.scale[1] * k, ob.scale[2])
    sc.frame_set(1)


PROBE_W = 320


def _probe(sc, frame, hide=()):
    """渲一张 320×180 的小图回来量。⛔ 这是「按结果调」的唯一依据，别靠猜。
    ⛔ img.pixels 拿到的是**线性**值（PNG 标了 sRGB，Blender 读进来会转），
       下面所有阈值（曝光 target、字色 bg）都是按线性定的，别和显示值混用。"""
    import bpy as _b
    import numpy as np
    old = (sc.render.resolution_x, sc.render.resolution_y, sc.render.resolution_percentage,
           sc.render.filepath, sc.eevee.taa_render_samples, sc.frame_current)
    was = [(o, o.hide_render) for o in hide]
    for o, _ in was:
        o.hide_render = True
    sc.render.resolution_x, sc.render.resolution_y = PROBE_W, int(PROBE_W * 9 / 16)
    sc.render.resolution_percentage = 100
    sc.eevee.taa_render_samples = 8
    # ⛔⛔ 探针文件名必须带 PID。并行渲染时三个 blender 进程都往同一个
    #    `%TEMP%\_bs_probe.png` 写、再读回来——0913 下午 S36 就这么挂的：
    #    写完正要 load，另一个进程把同名文件覆盖/占着，进程直接退出，
    #    **连 traceback 都没有**（chain.render 只打 stdout，stderr 被吞），
    #    表现成「frames=0，4 秒就 FAIL」。0912 两进程时没撞上，纯属运气。
    p = os.path.join(os.environ.get("TEMP", "."), "_bs_probe_%d.png" % os.getpid())
    sc.render.filepath = p[:-4]
    sc.frame_set(frame)
    _b.ops.render.render(write_still=True)
    img = _b.data.images.load(p)
    a = np.array(img.pixels[:], dtype=np.float32).reshape(sc.render.resolution_y, PROBE_W, 4)[::-1]
    _b.data.images.remove(img)
    for o, h in was:
        o.hide_render = h
    (sc.render.resolution_x, sc.render.resolution_y, sc.render.resolution_percentage,
     sc.render.filepath, sc.eevee.taa_render_samples) = old[:5]
    sc.frame_set(old[5])
    return np.clip(0.2126 * a[..., 0] + 0.7152 * a[..., 1] + 0.0722 * a[..., 2], 0, 8)


def _font_mats(sc):
    """标签（FONT）用到的材质集合。"""
    out = set()
    for ob in sc.objects:
        if ob.type != "FONT":
            continue
        try:
            for m in ob.data.materials:
                if m is not None:
                    out.add(m.name)
        except Exception:
            pass
    return out


def _scale_emission(k, skip=()):
    """把全场发光强度乘 k，**连关键帧一起乘**。

    ⛔ 发光材质是按「暗场里看不见暗物体」调的（emit_str 1~6）。新布光把场子提亮以后，
       这些发光体在 AgX 的高光段被压成白色、丢掉颜色身份（S80 三根柱子全白，柱身上的字全糊）。
       只改 default_value 不够——key_emit 打过关键帧的那些会照旧。
    """
    import bpy as _b
    for m in _b.data.materials:
        if not m.use_nodes or m.name in skip:
            continue      # ⛔ 标签是 UI，不能跟着场景一起调暗——S24 三个标签被缩到 0.26 倍，全糊在暗背景上
        for n in m.node_tree.nodes:
            if n.type != "BSDF_PRINCIPLED":
                continue
            try:
                inp = n.inputs["Emission Strength"]
            except KeyError:
                continue
            inp.default_value = float(inp.default_value) * k
        ad = m.node_tree.animation_data
        if ad and ad.action:
            for fc in ad.action.fcurves:
                if "Emission Strength" not in fc.data_path and not fc.data_path.endswith("default_value"):
                    continue
                for kp in fc.keyframe_points:
                    kp.co[1] *= k; kp.handle_left[1] *= k; kp.handle_right[1] *= k


def _content_mask(sc, cam, shape):
    """把**每个建模物体各自**的画面框画进一张 mask。

    ⛔ 不能用整体大框：S25 是一根斜放的内存条 + 一颗小芯片，整体框占了大半张画面，
       框里绝大多数是空的，量出来的 p75 就是背景电平——自动曝光会一路推到 ×42，
       整幅画面全白。逐物体的框贴身得多。
    """
    import numpy as np
    from bpy_extras.object_utils import world_to_camera_view
    from mathutils import Vector
    H, W = shape
    m = np.zeros((H, W), bool)
    for ob in sc.objects:
        if ob.hide_render or ob.type != "MESH":
            continue
        if any(ob.name.lower().startswith(s) for s in FIT_SKIP):
            continue
        try:
            nd = [world_to_camera_view(sc, cam, ob.matrix_world @ Vector(c)) for c in ob.bound_box]
        except Exception:
            continue
        if any(v.z <= 0 for v in nd):
            continue
        x0 = max(0.0, min(v.x for v in nd)); x1 = min(1.0, max(v.x for v in nd))
        y0 = max(0.0, min(v.y for v in nd)); y1 = min(1.0, max(v.y for v in nd))
        if x1 <= x0 or y1 <= y0:
            continue
        j0 = int(x0 * W); j1 = max(int(x1 * W), j0 + 1)
        i0 = int((1 - y1) * H); i1 = max(int((1 - y0) * H), i0 + 1)
        m[i0:i1, j0:j1] = True
    return m


def autoexpose(sc, cam, N, target=0.44, tries=5):
    """按渲出来的结果定曝光：主体像素的 75 分位打到 target（线性），灯和发光一起缩放。

    ⛔ 84 镜的 bs.lights(460,190,900) 这类常数是一镜一镜手调出来的，尺度一变全失准。
    """
    import numpy as np
    f = max(1, min(N, int(N * 0.6)))
    floors = [o for o in sc.objects if o.type == "MESH" and any(o.name.lower().startswith(s) for s in FIT_SKIP)]
    _EXPO["k"] = 1.0
    k_all = 1.0
    for _ in range(tries):
        g = _probe(sc, f, hide=floors)
        # ⛔ 主体掩膜不能用固定阈值。背景显示值约 0.11，写 0.05 会把整幅背景都算成主体，
        #    p75 永远偏低，曝光一路推到 ×9.8 把柱子全打成白的。先按 20 分位估背景电平。
        bgv = float(np.percentile(g, 20))
        m = g[g > bgv + 0.06]
        if m.size < g.size * 0.003:
            break      # ⛔ 阈值不能定在 1%：回闪类镜头主体本来就只占百分之几，
                       #    一放弃校正就整段发暗（S64 三站回闪就是这么黑掉的）
        cur = float(np.percentile(m, 75))
        # ⛔⛔ 只按「比背景亮 0.06 的像素」量，量到的其实是**自发光那部分**（线性 0.06 ≈ 显示 0.29，
        #    发光缝、标签、亮台子全在里头，靠灯照亮的机身根本进不了这个掩膜）。
        #    结果就是 S03：HBM 的发光缝很亮，曝光判「够了」，旁边的晶圆和内存条黑成一片，
        #    正好撞上用户第 3 条「光线很暗，所有建模并不能完整照亮」。
        #    所以再量一次**建模自己的画面框内**的 p75——框里包含没被照亮的机身，
        #    两个取小的那个，发光件就抢不走曝光了。
        import bpy as _b2
        sc.frame_set(f); _b2.context.view_layer.update()
        cm = _content_mask(sc, cam, g.shape)
        if cm.sum() > g.size * 0.01:
            cur = min(cur, float(np.percentile(g[cm], 75)))
        blown = float((g > 0.97).mean())
        if blown > 0.04:                       # 过曝面积超过 4% 一律先压下来
            cur = max(cur, target * (1.0 + blown * 6))
        print("   曝光探针: 主体 %.1f%%  p75=%.3f  过曝 %.1f%%" % (100 * m.size / g.size, cur, 100 * blown), flush=True)
        # ⛔ AgX 的高光肩部很平：显示值 0.9 往 0.44 压，场景线性光要降一个数量级。
        #    直接用 target/cur 当步长要跑七八轮，加个 1.9 次方两三轮就到。
        k = (target / max(cur, 1e-3)) ** 1.9
        k = max(0.10, min(3.0, k))
        if 0.93 < k < 1.07:
            break
        for o in sc.objects:
            if o.type == "LIGHT":
                o.data.energy *= k
        _scale_emission(k, _font_mats(sc))
        k_all *= k
    # ⛔⛔ 循环最后一步之后没人再看一眼——S25 就是这么连推四轮 ×3、渲出来整幅纯白的。
    #    收尾必须再探一次：过曝面积压不到 6% 以下就一路往回收。
    for _ in range(4):
        g = _probe(sc, f, hide=floors)
        blown = float((g > 0.97).mean())
        if blown <= 0.06:
            break
        k = max(0.25, 0.55 ** (1 + blown * 4))
        print("   ⚠ 收尾过曝 %.1f%% → 回收 ×%.2f" % (100 * blown, k), flush=True)
        for o in sc.objects:
            if o.type == "LIGHT":
                o.data.energy *= k
        _scale_emission(k, _font_mats(sc))
        k_all *= k
    _EXPO["k"] = k_all
    return k_all


def fix_text_pixels(sc, cam, N, gap=0.20):
    """字色按**渲出来的画面**定，不按材质猜。

    ⛔⛔ 用户「经常会有浅色建模+浅色字体的情况」。第一版用射线往字背后打、判那个物体的材质亮度——
       判错了：S70 四个青字压在发白的亮台子上，射线穿过去打到的是暗地板，判成「没问题」，
       实拍出来一个字看不见。现在把字全藏起来渲一张小图，直接量标签**将要落在的那块画面**。
    返回 (改了哪些, 需要加反色描边的名字集合)。
    """
    import numpy as np
    from bpy_extras.object_utils import world_to_camera_view
    from mathutils import Vector
    import bpy as _b
    fonts = [o for o in sc.objects if o.type == "FONT" and not o.hide_render]
    if not fonts:
        return [], set()
    fixed = []
    done = set()
    need_halo = set()
    for t in (0.35, 0.7, 0.95):
        f = max(1, min(N, int(N * t)))
        g = _probe(sc, f, hide=fonts)
        # ⛔ 判明暗必须在**显示空间**。_probe 回来的是线性值，那里 0.13 的绿板和 0.005 的背景
        #    差距被压扁，标准差算出来只有 0.06、够不到阈值——S01 的白标题压在浅绿板上就是这么漏的。
        g = np.where(g <= 0.0031308, g * 12.92, 1.055 * np.power(np.maximum(g, 1e-8), 1 / 2.4) - 0.055)
        H, W = g.shape
        sc.frame_set(f); _b.context.view_layer.update()
        for ob in fonts:
            if max(abs(v) for v in ob.scale) < 0.05:
                continue
            try:
                nd = [world_to_camera_view(sc, cam, ob.matrix_world @ Vector(c)) for c in ob.bound_box]
            except Exception:
                continue
            if any(v.z <= 0 for v in nd):
                continue
            x0 = max(0.0, min(v.x for v in nd)); x1 = min(1.0, max(v.x for v in nd))
            y0 = max(0.0, min(v.y for v in nd)); y1 = min(1.0, max(v.y for v in nd))
            j0, j1 = int(x0 * W), max(int(x1 * W), int(x0 * W) + 2)
            i0, i1 = int((1 - y1) * H), max(int((1 - y0) * H), int((1 - y1) * H) + 2)
            patch = g[max(0, i0 - 1):i1 + 1, max(0, j0 - 1):j1 + 1]
            if patch.size < 4:
                continue
            # ⛔ 取 70 分位会被少量高光带偏：S24 的句子压在「暗芯片 + 金色网格」上，
            #    p70 落在金线上判成「底子亮」→ 换深字 → 压在暗芯片体上一个字看不见。
            #    改用中位数：底子**大部分**亮才换深字，明暗混杂的交给反色描边。
            bg = float(np.percentile(patch, 50))
            sd = float(patch.std())
            name = ob.name
            if sd >= 0.13:                              # 明暗混杂（显示空间）
                need_halo.add(name)
            if name in done:
                continue
            # ⛔ 不做「已经够对比就跳过」的捷径：那要拿材质估的亮度和渲出来的亮度比，两把尺子不通用。
            col = _own_color(ob)
            # ⛔ 阈值不能低。相机一路在推近，标签背后那块画面一直在变，单次判定必然不准；
            #    而「深字 + 白描边」看起来像空心字（S24 的三个标签就是这样）。
            #    默认走「亮字 + 深描边」这个标准做法，只有底子**确实很亮**（>0.62）才换深字。
            # ⛔⛔ 底子「亮」还不够，还得**匀**。S04 的「为了这根板子，打了四十年」压在
            #    一排会亮起来的石碑顶边上：中位数被那条白边拉过 0.62 判成深字，
            #    可字大部分落在黑背景上，渲出来是一行灰字加白边——比浅色叠浅色更难看。
            #    明暗混杂的一律走「亮字 + 深描边」，描边本来就是为这种情况做的。
            # ⛔⛔ 门槛从 0.62 抬到 0.72：0.6 左右的中等亮面（S85 的三块碑、S04 的石板）
            #    换成深字并不会更清楚——深字配的白描边会把笔画糊成重影，比白字还难读。
            #    现在所有标签都带描边，中等亮面上「亮字 + 深描边」一律赢。只有真正发白的
            #    底子（>0.72，比如打亮的台面）才值得换深字。
            if bg > 0.72 and sd < 0.13:
                dk = (col[0] * 0.10, col[1] * 0.10, col[2] * 0.10, 1)
                ob.data.materials.clear()
                ob.data.materials.append(M("txtd_" + name, dk, rough=0.45))
                fixed.append((name, "深", round(bg, 2))); done.add(name)
            elif _mat_lum(ob) < 0.55:                   # 其余一律保证字够亮
                ob.data.materials.clear()
                ob.data.materials.append(M("txtl_" + name, col, emit=col, emit_str=3.0))
                fixed.append((name, "提亮", round(bg, 2))); done.add(name)
    sc.frame_set(1)
    return fixed, need_halo


def add_halos(sc, only=None):
    """给指定的 3D 标签加一圈**反色描边**：把字形膨胀一圈、涂成相反明度，垫在字后面。

    ⛔⛔ 只按「底子亮就换深字」修不够——一个标签常常同时压在亮台子和暗物体上
       （S70 的「晶圆」左半在暗晶圆上、右半在亮台子上，怎么选都有一半看不见）。
    描边做成字的**子物体**，所以 pop 关键帧、父级、位移全都自动跟着走。
    """
    import bpy as _b
    from mathutils import Matrix
    made = 0
    for ob in list(sc.objects):
        if ob.type != "FONT" or ob.name.endswith("_hl") or ob.hide_render:
            continue
        if only is not None and ob.name not in only:
            continue
        lum = _mat_lum(ob)
        d = ob.data.copy()
        # ⛔ 膨胀量要小：中文笔画密，0.05 会把字糊成一团白块
        d.offset = max(0.008, float(ob.data.size) * 0.028)
        d.materials.clear()
        if lum >= 0.40:                                          # 亮字 → 深描边
            d.materials.append(M("halo_d", (0.004, 0.006, 0.010, 1), rough=0.6))
        else:                                                    # 深字 → 亮描边
            d.materials.append(M("halo_l", WHITE, emit=WHITE, emit_str=2.0))
        h = _b.data.objects.new(ob.name + "_hl", d)
        sc.collection.objects.link(h)
        h.parent = ob
        h.matrix_parent_inverse = Matrix.Identity(4)
        h.location = (0.0, 0.0, -0.012)                          # 字形在局部 XY 面，−Z 就是「后面」
        made += 1
    return made


def go(sc, cam, B, key=1.0, fill=1.0, rim=1.0, top=1.0, expose=0.44):
    """每镜渲染前的统一收尾：取景 → 布光 → 定曝光 → 字色。四件全部量出来，不手调。"""
    m = fit(sc, cam, B.N)
    _stretch_floor(sc, cam, B.N)
    relight(sc, cam, B.N, key, fill, rim, top)
    k = autoexpose(sc, cam, B.N, expose)
    dim = _OPT.get("dim")
    if dim:
        # ⛔ relight() 会删掉所有灯重建，镜头里自己给灯打的关键帧会被抹掉（S09 的「关灯」中过）。
        #    所以「到某一帧把全场调暗」改成走这个开关，在重建之后统一打。
        f, factor, dur = dim
        for o in sc.objects:
            if o.type != "LIGHT":
                continue
            e = o.data.energy
            o.data.keyframe_insert("energy", frame=max(1, f - 2))
            o.data.energy = e * factor
            o.data.keyframe_insert("energy", frame=f + dur)
            o.data.energy = e
    fx, need_halo = fix_text_pixels(sc, cam, B.N)
    # ⛔ 描边给**所有**标签加，不只给明暗混杂的。字号 2% 的细描边在任何底子上都只会帮忙，
    #    而「这个标签有没有压在明暗交界上」随镜头运动一直在变，探针只抽三帧，判不准。
    hl = add_halos(sc)               # ⛔ 必须最后做：描边是字的副本，不能参与取景和字色测量
    dk = ["%s(%.2f)" % (n, bg) for n, how, bg in fx if how == "深"]
    print("  fit ×%.2f  曝光 ×%.2f  字色 %d 处%s  描边 %d 个"
          % (m, k, len(fx), ("（深字：%s）" % " ".join(dk)) if dk else "", hl), flush=True)
    return m


def M(name, *a, **kw):
    if name not in _M:
        _M[name] = L.mat(name, *a, **kw)
    return _M[name]


def reset_dark(preview=False, samples=32, bg=DARKBG):
    _M.clear(); _BASE.clear(); _OPT.clear(); _OPT["oblique"] = True
    sc = L.reset(samples=samples, preview=preview)
    sc.world.node_tree.nodes["Background"].inputs[0].default_value = bg
    if preview:                       # 预览只看取景，关光追和阴影，速度差一个数量级
        sc.eevee.use_raytracing = False
        sc.eevee.use_shadows = False
    return sc


# ---------- 通用材质 ----------
def m_pcb():      return M("pcb", (0.05, 0.16, 0.10, 1), rough=0.55)
def m_chip():     return M("chip", (0.10, 0.115, 0.145, 1), metallic=0.5, rough=0.44)
def m_metal():    return M("metal", (0.45, 0.48, 0.55, 1), metallic=1.0, rough=0.3)
def m_gold():     return M("gold", (0.85, 0.65, 0.2, 1), metallic=1.0, rough=0.25)
def m_si():       return M("si", (0.10, 0.13, 0.18, 1), metallic=0.65, rough=0.38)
def m_dim():      return M("dim", (0.12, 0.145, 0.19, 1), metallic=0.3, rough=0.6)
def m_glassc():   return M("glassc", CYAN, rough=0.15, alpha=0.16)
def m_glasso():   return M("glasso", ORANGE, rough=0.2, alpha=0.20)


def m_glow(name, color, s=6.0):
    return M("g_" + name, color, emit=color, emit_str=s)


def floor(z=-0.4, size=400):
    """⛔ 地板既不能太亮也不能纯黑。太亮（rough 0.85 的漫反射）会被照成画面里最亮的一块、
       对比度塌掉；纯黑（底色 0.006）又让主体稀疏的镜头整帧像空的（S03/S05 只有 8~10%
       的像素非背景，平均亮度 0.05）。定在反照率 0.016：主体脚下有一池淡光，远处仍然沉下去。
    原注：0911 晚 —— 地板不能是漫反射的。灯按内容尺度加强以后，rough=0.85 的地板会被照成
       画面里最亮的一块（实测平均亮度 0.31、比主体还抢眼），对比度整个塌掉。
       改成近黑的低漫反射金属面：它自己不亮，只把发光的主体反下来——就是「一池光」的效果。"""
    return L.box("floor", (size, size, 0.2), (0, 0, z - 0.1), M("floor", (0.016, 0.020, 0.030, 1), rough=0.88, metallic=0.0))


def lights(key=520, fill=150, rim=1200):
    k, f, r = L.lights(key * 1.7, fill * 2.2, rim * 0.55)
    import bpy as _b
    _b.ops.object.light_add(type="AREA", location=(0, -14, 8))
    c = _b.context.object; c.data.energy = key * 1.1; c.data.size = 14
    c.data.color = (0.85, 0.92, 1.0); L.look(c, (0, 0, 1.5))
    return k, f, r


# ---------- 内存条 ----------
def dimm(loc=(0, 0, 0), nchip=8, name="dimm", chips=True, glow_chip=None):
    """一根内存条：绿板 + 金手指 + 8 颗黑芯片。返回芯片列表。"""
    L.box(name, (13.3, 3.0, 0.16), loc, m_pcb(), bevel=0.03)
    for i in range(26):
        x = loc[0] - 6.1 + i * 0.49
        L.box("%s_f%d" % (name, i), (0.3, 0.5, 0.03), (x, loc[1] - 1.35, loc[2] - 0.09), m_gold())
    L.box("%s_notch" % name, (0.22, 0.7, 0.2), (loc[0] - 1.2, loc[1] - 1.3, loc[2]), M("notch", DARKBG))
    out = []
    if chips:
        for i in range(nchip):
            x = loc[0] - 5.4 + i * 1.55
            mm = m_glow("chip%s" % name, CYAN, 0.9) if glow_chip == i else m_chip()
            out.append(L.box("%s_c%d" % (name, i), (1.15, 1.55, 0.22), (x, loc[1] + 0.25, loc[2] + 0.19), mm, bevel=0.02))
    return out


def chip(name, loc, size=(1.15, 1.55, 0.22), m=None, label_dots=0):
    o = L.box(name, size, loc, m or m_chip(), bevel=0.02)
    if label_dots:
        for i in range(label_dots):
            L.box("%s_d%d" % (name, i), (size[0] * 0.6, 0.03, 0.006),
                  (loc[0], loc[1] - size[1] * 0.3 + i * size[1] * 0.6 / max(1, label_dots - 1), loc[2] + size[2] / 2 + 0.005),
                  m_glow("dots", CYAN, 1.6))
    return o


# ---------- 一个 DRAM 格子：开关 + 井 ----------
def cell(loc=(0, 0, 0), name="cell", h=4.0, r=0.34, wall_alpha=0.16, fill=0.0):
    """返回 dict(well=井壁, liquid=井里的电子柱, gate=开关, neck=井颈)。
    liquid 的原点在**井底**，z scale 用 L.key_scale 打关键帧就是水位（0=空，1=满）。"""
    x, y, z = loc
    d = {}
    d["sub"] = L.box(name + "_sub", (5.0, 3.2, 0.5), (x, y, z - 0.25), M("subs", (0.04, 0.05, 0.08, 1), rough=0.6))
    # 井（电容）：细长竖管，半透明壁
    d["well"] = L.cyl(name + "_w", r, h, (x, y, z + h / 2), M("wellw", CYAN, rough=0.12, alpha=wall_alpha))
    d["core"] = L.cyl(name + "_c", r * 0.78, h * 0.985, (x, y, z + h / 2), M("wellc", (0.02, 0.05, 0.08, 1), rough=0.3, alpha=0.35))
    # ⛔⛔ 0912 用户「光柱会超出底部」：水位是靠 `L.key_scale(liquid, ..., (1,1,f))` 做的，
    #    而缩放是**绕物体原点**的。原点原来在柱子中间，一放大就上下同时长——下半截直接穿出衬底。
    #    把网格整体往上挪半个高度，让原点落在**井底**，从此 scale.z 就是老老实实的「水位」。
    liq = L.cyl(name + "_l", r * 0.72, h * 0.94, (x, y, z + 0.02), m_glow("liq", CYAN, 7.0))
    from mathutils import Matrix as _Mx
    liq.data.transform(_Mx.Translation((0, 0, h * 0.94 / 2)))
    liq.scale = (1, 1, max(1e-3, fill))
    d["liquid"] = liq
    # 开关（晶体管）：井口上方的横向闸门
    d["gate"] = L.box(name + "_g", (1.5, 0.9, 0.28), (x, y, z + h + 0.35), M("gatem", (0.5, 0.53, 0.6, 1), metallic=1.0, rough=0.28), bevel=0.03)
    # ⛔ 0912 用户「井建模顶部为什么有个黄色的十字架」：原来这儿有字线和位线两根横杆交叉，
    #    又长又亮，看着就是个十字架；而口播里这一段只说「一个开关、一口井」两样东西，
    #    它们既没被讲到、也不在画面主线上。画面要和口播一字对上，所以去掉，只留闸门和井颈。
    d["neck"] = L.cyl(name + "_n", r * 0.5, 0.45, (x, y, z + h + 0.1), m_metal())
    return d


def electrons(n, name, center, spread, r=0.075, color=CYAN, s=8.0):
    import random
    out = []
    for i in range(n):
        p = (center[0] + random.uniform(-spread[0], spread[0]),
             center[1] + random.uniform(-spread[1], spread[1]),
             center[2] + random.uniform(-spread[2], spread[2]))
        out.append(L.sphere("%s_e%d" % (name, i), r, p, m_glow("elec", color, s), sub=1))
    return out


def wellgrid(nx, ny, name="wg", pitch=1.0, h=2.2, r=0.2, loc=(0, 0, 0), lit=()):
    """一片井阵列（俯视像点阵，侧看像森林）。lit 是要发光的 (i,j) 集合。"""
    out = {}
    x0 = loc[0] - (nx - 1) * pitch / 2
    y0 = loc[1] - (ny - 1) * pitch / 2
    dull = M("wgd", (0.07, 0.10, 0.14, 1), metallic=0.25, rough=0.62)
    hot = m_glow("wgh", CYAN, 6.0)
    for i in range(nx):
        for j in range(ny):
            o = L.cyl("%s_%d_%d" % (name, i, j), r, h, (x0 + i * pitch, y0 + j * pitch, loc[2] + h / 2),
                      hot if (i, j) in lit else dull)
            out[(i, j)] = o
    return out


# ---------- 晶圆 / 颗粒 ----------
def wafer(name="wafer", r=8.0, loc=(0, 0, 0), nx=13, ny=13, die=1.05, notch=True):
    L.cyl(name, r, 0.12, loc, M("waf", (0.17, 0.21, 0.27, 1), metallic=0.5, rough=0.38))
    dies = []
    md = M("wdie", (0.12, 0.15, 0.20, 1), metallic=0.45, rough=0.45)
    for i in range(nx):
        for j in range(ny):
            x = loc[0] + (i - (nx - 1) / 2) * die * 1.06
            y = loc[1] + (j - (ny - 1) / 2) * die * 1.06
            if math.hypot(x - loc[0], y - loc[1]) > r - die * 0.85:
                continue
            dies.append(L.box("%s_d%d_%d" % (name, i, j), (die, die, 0.05), (x, y, loc[2] + 0.085), md, bevel=0.008))
    if notch:
        L.box(name + "_n", (0.5, 0.5, 0.2), (loc[0], loc[1] - r, loc[2]), M("wnotch", DARKBG), rot=(0, 0, math.pi / 4))
    return dies


# ---------- HBM 楼 ----------
def stack(name, loc, layers=12, th=0.16, gap=0.08, w=2.4, d=2.0, tsv=True, base=True, seam=True):
    """一栋 HBM：base die + N 层 DRAM，层间发光缝，贯穿的硅通孔。返回 (层列表, 顶面 z)。"""
    x, y, z = loc
    zs = z
    if base:
        L.box(name + "_b", (w * 1.05, d * 1.05, 0.26), (x, y, zs + 0.13), M("hbase", (0.06, 0.08, 0.12, 1), metallic=0.8, rough=0.3), bevel=0.02)
        zs += 0.26
    lay = []
    for k in range(layers):
        zc = zs + gap + k * (th + gap) + th / 2
        lay.append(L.box("%s_%d" % (name, k), (w, d, th), (x, y, zc), m_chip(), bevel=0.012))
        if seam:
            L.box("%s_s%d" % (name, k), (w * 1.02, d * 1.02, 0.014), (x, y, zc - th / 2 - gap / 2), m_glow("seam", CYAN, 3.0))
    top = zs + gap + layers * (th + gap)
    if tsv:
        for i in range(4):
            for j in range(5):
                L.cyl("%s_t%d_%d" % (name, i, j), 0.035, top - z - 0.1,
                      (x - 0.75 + i * 0.5, y - 0.7 + j * 0.35, z + 0.05 + (top - z - 0.1) / 2), m_glow("tsv", CYAN, 9.0))
    return lay, top


def interposer(name="itp", loc=(0, 0, 0), w=20.0, d=13.0, traces=True):
    L.box(name, (w, d, 0.3), loc, m_si(), bevel=0.03)
    if traces:
        tr = m_glow("trace", CYAN, 1.6)
        for i in range(24):
            y = loc[1] - d * 0.44 + i * d * 0.88 / 23
            L.box("%s_t%d" % (name, i), (w * 0.72, 0.04, 0.02), (loc[0] + w * 0.1, y, loc[2] + 0.16), tr)
        for i in range(12):
            x = loc[0] - w * 0.42 + i * w * 0.84 / 11
            L.box("%s_v%d" % (name, i), (0.035, d * 0.8, 0.02), (x, loc[1], loc[2] + 0.16), tr)
    return name


def gpu_die(name="gpu", loc=(0, 0, 0), s=6.0, hot=False):
    L.box(name, (s, s, 0.55), (loc[0], loc[1], loc[2] + 0.28), M("gpud", (0.05, 0.065, 0.095, 1), metallic=0.7, rough=0.5), bevel=0.04)
    mo = m_glow("gcore", ORANGE, 2.6 if hot else 1.4)
    for i in range(11):
        L.box("%s_r%d" % (name, i), (s * 0.82, 0.06, 0.012), (loc[0], loc[1] - s * 0.41 + i * s * 0.82 / 10, loc[2] + 0.565), mo)
    for i in range(11):
        L.box("%s_c%d" % (name, i), (0.05, s * 0.82, 0.012), (loc[0] - s * 0.41 + i * s * 0.82 / 10, loc[1], loc[2] + 0.565), mo)
    return name


# ---------- 机械硬盘（仓库） ----------
def hdd(name="hdd", loc=(0, 0, 0), scale=1.0):
    s = scale
    L.box(name, (10 * s, 7 * s, 0.9 * s), loc, M("hddc", (0.13, 0.14, 0.16, 1), metallic=0.9, rough=0.35), bevel=0.05)
    L.cyl(name + "_p", 3.1 * s, 0.12 * s, (loc[0] - 0.6 * s, loc[1], loc[2] + 0.52 * s), M("platter", (0.72, 0.75, 0.80, 1), metallic=0.9, rough=0.28))
    L.cyl(name + "_p2", 1.0 * s, 0.14 * s, (loc[0] - 0.6 * s, loc[1], loc[2] + 0.55 * s), M("platter2", (0.30, 0.33, 0.38, 1), metallic=0.9, rough=0.35))
    L.cyl(name + "_h", 0.35 * s, 0.3 * s, (loc[0] - 0.6 * s, loc[1], loc[2] + 0.6 * s), m_metal())
    L.box(name + "_a", (3.4 * s, 0.35 * s, 0.1 * s), (loc[0] + 1.6 * s, loc[1] + 1.2 * s, loc[2] + 0.6 * s), m_metal(), rot=(0, 0, -0.5))
    return name


def shelf(name="shelf", loc=(0, 0, 0), cols=4, rows=3, box_m=None):
    """仓库货架：一排排格子，里面塞着箱子。"""
    fr = M("shelffr", (0.30, 0.33, 0.38, 1), metallic=0.5, rough=0.5)
    bm = box_m or M("carton", (0.52, 0.40, 0.25, 1), rough=0.7)
    out = []
    for r in range(rows):
        z = loc[2] + r * 2.2
        L.box("%s_s%d" % (name, r), (cols * 2.4, 1.8, 0.12), (loc[0], loc[1], z), fr)
        for c in range(cols):
            x = loc[0] - (cols - 1) * 1.2 + c * 2.4
            out.append(L.box("%s_b%d_%d" % (name, r, c), (1.6, 1.3, 1.5), (x, loc[1], z + 0.81), bm, bevel=0.03))
    for sx in (-1, 1):
        L.box("%s_p%d" % (name, sx), (0.18, 1.9, rows * 2.2 + 0.6), (loc[0] + sx * cols * 1.2, loc[1], loc[2] + rows * 1.1), fr)
    return out


def desk(name="desk", loc=(0, 0, 0), w=12.0, d=7.0):
    L.box(name, (w, d, 0.25), loc, M("desktop", (0.07, 0.085, 0.115, 1), metallic=0.1, rough=0.8), bevel=0.04)
    L.box(name + "_edge", (w * 1.005, d * 1.005, 0.02), (loc[0], loc[1], loc[2] + 0.14), m_glow("dedge", CYAN, 0.45))
    return name


def cage_box(name, loc, s=1.4, m=None):
    """固态硬盘那期的「电子笼子」，本片只在对照时出现一次。"""
    m = m or M("cagem", ORANGE, metallic=0.3, rough=0.3, alpha=0.42)
    b = L.box(name, (s, s, s * 0.72), (loc[0], loc[1], loc[2] + s * 0.36), m, bevel=0.03)
    L.box(name + "_f", (s * 1.07, s * 1.07, 0.06), (loc[0], loc[1], loc[2] + s * 0.75), m_metal(), bevel=0.02)
    return b


# ---------- 图形化小件 ----------
def bar(name, loc, h, w=1.2, color=CYAN, glow=1.0):
    return L.box(name, (w, w, max(h, 1e-3)), (loc[0], loc[1], loc[2] + h / 2), m_glow("bar_" + name, color, glow))


def ring(name, r=6.0, n=6, z=0.0, color=CYAN):
    """正反馈环：n 个节点排成圆，节点之间用弧线连。返回节点列表。"""
    nodes = []
    for i in range(n):
        a = math.pi / 2 - i * 2 * math.pi / n
        p = (r * math.cos(a), r * math.sin(a), z)
        nodes.append(L.cyl("%s_n%d" % (name, i), 1.15, 0.22, p, M("ringn", (0.08, 0.12, 0.18, 1), metallic=0.6, rough=0.35)))
    seg = M("ringseg", (0.10, 0.16, 0.22, 1), metallic=0.5, rough=0.4)
    arcs = []
    for i in range(n):
        a0 = math.pi / 2 - i * 2 * math.pi / n
        a1 = math.pi / 2 - (i + 1) * 2 * math.pi / n
        grp = []
        for k in range(9):
            t = (k + 0.5) / 9
            a = a0 + (a1 - a0) * t
            grp.append(L.cyl("%s_a%d_%d" % (name, i, k), 0.10, 0.9, (r * math.cos(a), r * math.sin(a), z),
                             seg, rot=(math.pi / 2, 0, -a)))
        arcs.append(grp)
    return nodes, arcs


def glyph(name, ch, loc, cam, size=0.8, color=CYAN, strength=3.0):
    return L.text(name, ch, loc, size, color, strength, align="CENTER", face_cam=cam)


def caption(name, body, loc, cam, size=0.55, color=CYAN, appear=None, align="CENTER"):
    return L.label(name, body, loc, cam, size=size, color=color, appear=appear, align=align)
