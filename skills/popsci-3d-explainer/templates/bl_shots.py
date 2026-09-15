# -*- coding: utf-8 -*-
"""镜头函数。一个函数 = 一镜 = scenes.py 里的一块 = 格子法里的一格「画」。

    blender.exe -b --python bl_shots.py -- S11 <输出目录> [preview]

时间全部来自 BEATS_JSON（`make.py beats` 的产物）：
    B.N            这一镜的总帧数（= 这一块口播的长度 + 0.5 秒）
    B.f("词")      那个词**开口**的帧号（已提前 4 帧，模仿「元素出现 = 字幕块起始 −6…+3」）
    B.end("词")    那个词说完的帧号
    B.frac(0.42)   按比例取帧（找不到关键词时的兜底）

三条纪律（来自 skill beat-driven-explainer，实测差距全在这里）：
  ① **每镜一个主角**，占画面高 ≥1/3；配角 ≤4、标签 ≤6。
  ② **只有主角发光**（emit_str 只给主角，且别超过 2——超了会烧成纯白块）。
  ③ **每句至少一处可察觉的变化**；静止超过 45 帧就加一次推近（30~45 帧 easeInOut）。

⛔⛔ 拍点词必须真的在那一块口播里（`check_beats_kw.py` 会查）。找不到只会**静默退回默认帧**。
⛔ 拍点别打在整块的**最后三个字**上——动作还没做完口播就结束了，露脸不到一秒。
   打在短语开头：动作先发生，名字随后落。
"""
import math, os, random, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bpy  # noqa: E402
import bl_lib as L  # noqa: E402
import bl_scene as bs  # noqa: E402
from bl_lib import CYAN, ORANGE, GOLD, RED, GREEN, WHITE, GREY  # noqa: E402

random.seed(7)


def _b(seg, n=270):
    return L.beats(seg, n)


def _go(sc, out, B):
    """每一镜的收尾：自动取景 → 按内容尺度布光 → 自动曝光 → 字色纠正 → 渲。

    ⛔⛔ 这四件**一律不手写常数**。场景尺度从 13 到 400 差三十倍、相机又被 fit() 退到任意远，
       手写的 `lights(460,190,900)` 在下一镜必然失准（实测全片平均亮度中位只有 0.088）。
    """
    bs.go(sc, bpy.context.scene.camera, B)
    L.render(sc, out, 1, B.N)


def push(cam, B, a, b, ta, tb=None, lens=None, f0=1, f1=None):
    """一镜只推一次：从 a 推到 b。⛔ 一镜多次运镜会让观众晕，且每章 ≥3 次、每镜 ≤1 次是硬配额。"""
    L.key_cam(cam, f0, a, ta, lens)
    L.key_cam(cam, f1 or B.N, b, tb or ta, lens)


# ================= p01 =================
# ⛔ 每个 B.f("…") 的词必须出现在 scenes.py 里对应那一块的口播中。改稿之后跑 check_beats_kw.py。
def S01(out, preview):
    """示例①：一个主角 + 一次缓推 + 一个按拍点弹出的标签。

    口播：「先看一个数字：这东西一年涨了四倍。」
    """
    B = _b("S01a", 200)
    sc = bs.reset_dark(preview)          # preview=True 关光追和阴影：一镜 18 秒；开着要 6 分钟
    bs.lights(); bs.floor(-0.3, 120)
    bs.dimm((0, 0, 0))                   # ← 换成你自己的零件
    # ⛔ 正面平拍一根细长的东西 = 内容宽高比 1.9:1，主体只占画面高 25%，相机怎么调都救不回来。
    #    低机位斜着看，让它沿对角线穿过画面，透视一压长度就够了。
    cam = L.camera((-9.5, -7.6, 3.0), (1.5, 0, 0.5), lens=36, fstop=2.8, focus=12)
    push(cam, B, (-10.5, -8.4, 3.4), (-6.0, -6.0, 2.2), (1.5, 0, 0.5))
    L.label("q", "一年四倍", (0, 2.4, 1.7), cam, size=0.8, color=ORANGE,
            appear=B.f("一年涨了", B.frac(0.5)), align="CENTER")
    _go(sc, out, B)


def S02(out, preview):
    """示例②：一摞东西按拍点逐层落下来。

    口播：「但问题来了，它凭什么？」

    ⛔ `L.key_loc` 会**就地修改** o.location：先写「抬高 5」再拿 tuple(o.location) 当落点，
       读到的已经是抬高后的值，整摞永远不落地。**落点必须先存下来。**
    ⛔ 还没出场的物体要 `L.hide` 掉——取景只按 MESH 外接框算，吊在天上等着落位的东西也算在框里，
       相机只能一路退（实测主体只占画面高一成半）。但起手也不能全 hide：第一帧全黑会被空场检查报。
    """
    B = _b("S02a", 260)
    sc = bs.reset_dark(preview); bs.lights(); bs.floor(-0.3, 160)
    lay, top = bs.stack("h", (0, 0, 0), layers=8, w=4.4, d=3.8)
    homes = [tuple(o.location) for o in lay]          # ← 先存落点
    f = B.f("凭什么", 20)
    for i, o in enumerate(lay):
        if i >= 2:                                     # 底座和头两层第 1 帧就摆着，免得开场全黑
            L.hide(o, 1, True); L.hide(o, f + i * 6 - 1, False)
        L.key_loc(o, f + i * 6, (homes[i][0], homes[i][1], homes[i][2] + 5))
        L.key_loc(o, f + i * 6 + 18, homes[i])
    cam = L.camera((8.5, -13, 5.2), (0, 0, top / 2), lens=42, fstop=3.0, focus=16)
    L.orbit(cam, (0, 0, top / 2), 15.6, 2.2, -58, -34, 1, B.N, lens=42)
    # ⛔ 往天上挂字之前先算一遍：取景按 MESH 框的**宽度**定，16:9 下竖向只覆盖「框宽 × 9/16」。
    #    「框宽 × 9/16 − 主体高」不够 2 个单位就别往天上挂——排版工序会把字拉回来压在主体上。
    L.label("t", "一层一层叠上去", (0, 0, top + 1.6), cam, size=0.66, color=WHITE,
            appear=B.f("问题来了", B.frac(0.4)), align="CENTER")
    _go(sc, out, B)


# ================= p02 =================
def S03(out, preview):
    """示例③：最短的一镜——一个主角、一次推近，没有标签。

    口播：「这是第二段的第一块。」
    """
    B = _b("S03a", 150)
    sc = bs.reset_dark(preview); bs.lights(); bs.floor(-0.3, 120)
    bs.wafer("w", r=6.0)
    cam = L.camera((7, -11, 6), (0, 0, 0), lens=40, fstop=3.0, focus=14)
    push(cam, B, (7.6, -12.0, 6.6), (5.0, -8.0, 4.2), (0, 0, 0))
    _go(sc, out, B)


def S04(out, preview):
    """示例④：配角灰着、只有主角发光。

    口播：「再往下看，就是第二块了。」
    """
    B = _b("S04a", 150)
    sc = bs.reset_dark(preview); bs.lights(); bs.floor(-0.3, 120)
    bs.chip("c1", (-3.0, 0, 0))                       # 配角：不发光
    hero = bs.chip("c2", (0.6, 0, 0), m=bs.m_glow("hero", CYAN, 0.9))   # ⛔ emit 别超过 2
    cam = L.camera((5.5, -9, 4.2), (0, 0, 0), lens=45, fstop=2.8, focus=11)
    push(cam, B, (6.0, -9.6, 4.6), (3.6, -6.4, 3.0), (0, 0, 0))
    L.label("t", "只有主角发光", (0.6, 0, 2.2), cam, size=0.5, color=WHITE,
            appear=B.f("再往下看", 10), align="CENTER")
    _go(sc, out, B)


# ---- 调度：镜头名 → 函数 ------------------------------------------------------
SHOTS = {k: v for k, v in list(globals().items()) if callable(v) and len(k) >= 2 and k[0] == "S" and k[1].isdigit()}

if __name__ == "__main__":
    a = sys.argv[sys.argv.index("--") + 1:]
    shot, outd = a[0], a[1]
    prev = len(a) > 2 and a[2] == "preview"
    # 镜头拆到多个文件时，在这里把它们的 SHOTS 合进来，**并同步登进 config.json 的 shot_files**
    # （⛔ 漏登 = 格子法盖假章，见 shots.generator_fingerprint）。
    import importlib.util
    import config as C
    for p in C.shot_paths()[1:]:
        spec = importlib.util.spec_from_file_location("_s_" + os.path.basename(p)[:-3], p)
        m = importlib.util.module_from_spec(spec); sys.modules[spec.name] = m
        spec.loader.exec_module(m); SHOTS.update(m.SHOTS)
    SHOTS[shot](outd, prev)
