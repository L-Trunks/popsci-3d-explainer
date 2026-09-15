# -*- coding: utf-8 -*-
"""Blender headless 场景库（bpy）。所有镜头脚本 import 这份。

    blender.exe -b --python bl_shots.py -- <镜号> <输出目录> [preview]
"""
import bpy, math, os, sys
from mathutils import Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import config as _C
    FONT, FPS = _C.FONT_UI, _C.FPS
except Exception:            # blender 里 config.json 缺失时也要能跑
    FONT = r"C:\Windows\Fonts\msyhbd.ttc"
    FPS = 30

CYAN = (0.15, 0.9, 1.0, 1)
ORANGE = (1.0, 0.55, 0.1, 1)
GOLD = (0.9, 0.7, 0.25, 1)
RED = (1.0, 0.2, 0.15, 1)
GREEN = (0.3, 1.0, 0.4, 1)
WHITE = (1, 1, 1, 1)
GREY = (0.5, 0.5, 0.55, 1)


def reset(res=(1920, 1080), samples=64, preview=False):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.render.engine = "BLENDER_EEVEE_NEXT"
    sc.render.fps = FPS
    if preview:
        sc.render.resolution_x, sc.render.resolution_y = 640, 360
        sc.eevee.taa_render_samples = 16
        sc.frame_step = int(os.environ.get("BL_STEP", "25"))
    else:
        sc.render.resolution_x, sc.render.resolution_y = res
        sc.eevee.taa_render_samples = samples
    sc.render.image_settings.file_format = "PNG"
    sc.render.image_settings.color_mode = "RGB"
    sc.render.film_transparent = False
    sc.eevee.use_shadows = True
    sc.eevee.use_raytracing = True
    sc.view_settings.view_transform = "AgX"
    sc.view_settings.look = "AgX - Medium High Contrast"
    w = bpy.data.worlds.new("w"); sc.world = w; w.use_nodes = True
    w.node_tree.nodes["Background"].inputs[0].default_value = (0.012, 0.014, 0.02, 1)
    w.node_tree.nodes["Background"].inputs[1].default_value = 1.0
    # 辉光：Eevee Next 没有 bloom，用合成器 Glare
    sc.use_nodes = True
    nt = sc.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    rl = nt.nodes.new("CompositorNodeRLayers")
    gl = nt.nodes.new("CompositorNodeGlare")
    gl.glare_type = "BLOOM"
    try:
        gl.inputs["Threshold"].default_value = 1.0
        gl.inputs["Strength"].default_value = 0.08
        gl.inputs["Size"].default_value = 0.6
    except Exception:
        gl.threshold = 1.0; gl.mix = -0.7
    out = nt.nodes.new("CompositorNodeComposite")
    nt.links.new(rl.outputs["Image"], gl.inputs["Image"])
    nt.links.new(gl.outputs["Image"], out.inputs["Image"])
    return sc


def frames(sc, start, end):
    sc.frame_start, sc.frame_end = start, end


# ---------- 材质 ----------
def mat(name, color=GREY, metallic=0.0, rough=0.5, emit=None, emit_str=0.0, alpha=1.0, transmission=0.0):
    m = bpy.data.materials.new(name); m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = color
    b.inputs["Metallic"].default_value = metallic
    b.inputs["Roughness"].default_value = rough
    b.inputs["Emission Color"].default_value = emit or color
    b.inputs["Emission Strength"].default_value = emit_str
    b.inputs["Alpha"].default_value = alpha
    b.inputs["Transmission Weight"].default_value = transmission
    if alpha < 1.0 or transmission > 0:
        m.blend_method = "BLEND"
        try:
            m.surface_render_method = "BLENDED"
        except Exception:
            pass
    return m


def glow(name, color, strength=6.0):
    return mat(name, color, emit=color, emit_str=strength)


def key_emit(obj, frame, strength, slot=0):
    m = obj.data.materials[slot]
    inp = m.node_tree.nodes["Principled BSDF"].inputs["Emission Strength"]
    inp.default_value = strength
    inp.keyframe_insert("default_value", frame=frame)


def key_alpha(obj, frame, alpha, slot=0):
    m = obj.data.materials[slot]
    inp = m.node_tree.nodes["Principled BSDF"].inputs["Alpha"]
    inp.default_value = alpha
    inp.keyframe_insert("default_value", frame=frame)


def key_color(obj, frame, color, slot=0):
    m = obj.data.materials[slot]
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = color
    b.inputs["Base Color"].keyframe_insert("default_value", frame=frame)
    b.inputs["Emission Color"].default_value = color
    b.inputs["Emission Color"].keyframe_insert("default_value", frame=frame)


# ---------- 几何 ----------
def box(name, size, loc, m, rot=(0, 0, 0), bevel=0.0):
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc)
    o = bpy.context.object; o.name = name
    o.scale = (size[0], size[1], size[2]); o.rotation_euler = rot
    o.data.materials.append(m)
    if bevel > 0:
        md = o.modifiers.new("bv", "BEVEL"); md.width = bevel; md.segments = 3
    return o


def sphere(name, r, loc, m, sub=2):
    bpy.ops.mesh.primitive_ico_sphere_add(radius=r, subdivisions=sub, location=loc)
    o = bpy.context.object; o.name = name
    o.data.materials.append(m)
    bpy.ops.object.shade_smooth()
    return o


def cyl(name, r, depth, loc, m, rot=(0, 0, 0)):
    bpy.ops.mesh.primitive_cylinder_add(radius=r, depth=depth, location=loc, rotation=rot)
    o = bpy.context.object; o.name = name
    o.data.materials.append(m)
    bpy.ops.object.shade_smooth()
    return o


def line(name, a, b, r, m):
    a, b = Vector(a), Vector(b)
    d = b - a
    o = cyl(name, r, d.length, (a + b) / 2, m)
    o.rotation_euler = d.to_track_quat("Z", "Y").to_euler()
    return o


# ---------- 文字 / 标签 ----------
_font = None


def text(name, body, loc, size=0.4, color=WHITE, strength=2.0, align="LEFT", face_cam=None, extrude=0.0):
    global _font
    if _font is None:
        _font = bpy.data.fonts.load(FONT)
    bpy.ops.object.text_add(location=loc)
    t = bpy.context.object; t.name = name
    t.data.body = body; t.data.font = _font; t.data.size = size
    t.data.align_x = align; t.data.extrude = extrude
    t.data.materials.append(glow(name + "_m", color, strength))
    if face_cam is None:
        t.rotation_euler = (1.35, 0, 0)
    else:
        c = t.constraints.new("TRACK_TO"); c.target = face_cam
        c.track_axis = "TRACK_Z"; c.up_axis = "UP_Y"
    return t


def label(name, body, loc, cam, size=0.32, color=CYAN, appear=None, vanish=None, anchor=None, strength=2.5, align="LEFT"):
    """浮在空间里的标签，面向相机；appear/vanish 给帧号做缩放出现/消失；anchor 给零件坐标画引线。"""
    t = text(name, body, loc, size, color, strength, align=align, face_cam=cam)
    objs = [t]
    if anchor is not None:
        ln = line(name + "_ln", loc, anchor, 0.008, glow(name + "_lm", color, 2.0))
        dot = sphere(name + "_dot", 0.03, anchor, glow(name + "_dm", color, 4.0), sub=1)
        objs += [ln, dot]
    if appear is not None:
        for o in objs:
            pop(o, appear)
    if vanish is not None:
        for o in objs:
            pop(o, vanish, out=True)
    return t


def pop(o, frame, out=False, dur=8):
    s = tuple(o.scale)
    if out:
        o.scale = s; o.keyframe_insert("scale", frame=frame)
        o.scale = (0, 0, 0); o.keyframe_insert("scale", frame=frame + dur)
        o.scale = s
    else:
        o.scale = (0, 0, 0); o.keyframe_insert("scale", frame=frame - 1)
        o.scale = s; o.keyframe_insert("scale", frame=frame + dur)


# ---------- 相机 / 灯 ----------
def camera(loc, target, lens=50, fstop=None, focus=None):
    bpy.ops.object.camera_add(location=loc)
    cam = bpy.context.object; cam.name = "cam"
    cam.data.lens = lens
    bpy.context.scene.camera = cam
    look(cam, target)
    if fstop:
        cam.data.dof.use_dof = True; cam.data.dof.aperture_fstop = fstop
        cam.data.dof.focus_distance = focus or (Vector(target) - Vector(loc)).length
    return cam


def look(cam, target):
    d = Vector(target) - cam.location
    cam.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()


def key_cam(cam, frame, loc, target=None, lens=None):
    cam.location = loc
    cam.keyframe_insert("location", frame=frame)
    if target is not None:
        look(cam, target)
        cam.keyframe_insert("rotation_euler", frame=frame)
    if lens is not None:
        cam.data.lens = lens
        cam.data.keyframe_insert("lens", frame=frame)


def orbit(cam, target, r, h, a0, a1, f0, f1, lens=None, steps=24):
    """绕 target 的水平环绕，a 是角度（度），逐步打关键帧避免旋转插值走捷径。"""
    for i in range(steps + 1):
        t = i / steps
        a = math.radians(a0 + (a1 - a0) * t)
        f = round(f0 + (f1 - f0) * t)
        key_cam(cam, f, (target[0] + r * math.cos(a), target[1] + r * math.sin(a), target[2] + h), target, lens)


def lights(key=1500, fill=400, rim=900):
    bpy.ops.object.light_add(type="AREA", location=(4, -5, 6)); k = bpy.context.object
    k.data.energy = key; k.data.size = 4; k.data.color = (1, 0.95, 0.9)
    bpy.ops.object.light_add(type="AREA", location=(-5, -3, 3)); f = bpy.context.object
    f.data.energy = fill; f.data.size = 6; f.data.color = (0.7, 0.85, 1)
    bpy.ops.object.light_add(type="AREA", location=(0, 6, 4)); r = bpy.context.object
    r.data.energy = rim; r.data.size = 3; r.data.color = (0.5, 0.8, 1)
    for l in (k, f, r):
        look(l, (0, 0, 0))
    return k, f, r


# ---------- 关键帧 ----------
def key_loc(o, frame, loc):
    o.location = loc; o.keyframe_insert("location", frame=frame)


def key_scale(o, frame, s):
    o.scale = s if isinstance(s, tuple) else (s, s, s); o.keyframe_insert("scale", frame=frame)


def key_rot(o, frame, rot):
    o.rotation_euler = rot; o.keyframe_insert("rotation_euler", frame=frame)


def linear(o):
    if o.animation_data and o.animation_data.action:
        for fc in o.animation_data.action.fcurves:
            for kp in fc.keyframe_points:
                kp.interpolation = "LINEAR"


def hide(o, frame, on=True):
    o.hide_render = on; o.keyframe_insert("hide_render", frame=frame)
    o.hide_viewport = on; o.keyframe_insert("hide_viewport", frame=frame)


# ---------- 渲染 ----------
def render(sc, out_dir, start=None, end=None):
    os.makedirs(out_dir, exist_ok=True)
    if start is not None:
        sc.frame_start, sc.frame_end = start, end
    sc.render.filepath = os.path.join(out_dir, "f_")
    bpy.ops.render.render(animation=True)
    n = len([f for f in os.listdir(out_dir) if f.endswith(".png")])
    print("RENDER_DONE frames=%d dir=%s" % (n, out_dir), flush=True)


# ---------- 拍点（beat-driven-explainer）：make.py beats → work/film/beats.json ----------
class Beats:
    def __init__(self, d, N_default):
        d = d or {}
        self.N = int(d.get("N", N_default)); self.text = d.get("text", ""); self.t = d.get("t", [])

    def f(self, kw, default=None, nth=0, lead=4):
        """关键词开口那一帧（提前 lead 帧，模仿「元素出现帧 = 字幕块起始帧 −6…+3」）；找不到返回 default。"""
        i = -1; start = 0
        for _ in range(nth + 1):
            i = self.text.find(kw, start)
            if i < 0:
                break
            start = i + 1
        if i < 0 or i >= len(self.t):
            return default if default is not None else 1
        return max(1, int(round(self.t[i][0] * FPS)) - lead)

    def end(self, kw, default=None):
        """关键词说完那一帧。"""
        i = self.text.find(kw)
        if i < 0 or i + len(kw) - 1 >= len(self.t):
            return default if default is not None else self.N
        return int(round(self.t[i + len(kw) - 1][1] * FPS))

    def frac(self, x):
        return max(1, int(round(self.N * x)))


def beats(seg, N_default=300):
    import json as _json
    p = os.environ.get("BEATS_JSON") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "work", "film", "beats.json")
    if os.path.exists(p):
        d = _json.load(open(p, encoding="utf-8")).get(seg)
        if d:
            return Beats(d, N_default)
    return Beats(None, N_default)
