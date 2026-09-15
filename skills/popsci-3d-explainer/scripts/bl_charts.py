# -*- coding: utf-8 -*-
"""3D 图表零件库（0911 用户第 2 条：纯文本卡改成建模的动态图表）。

三条纪律：
  ⛔ 名字写在柱体/圆盘**自己身上**，不是飘在旁边（用户点名要的）。
  ⛔ 贴在会亮起来的物体上的字一律**深色不发光**——白字在亮面上看不清（用户点名要的）。
  ⛔ 一屏只有主角发光，配角灰着；数值跟着柱子长出来，不是一开始就杵在那。
"""
import math

import bpy
import bl_lib as L
import bl_scene as bs
from bl_lib import CYAN, ORANGE, GOLD, WHITE, GREY

DARK = (0.012, 0.018, 0.028, 1)
PLATE = (0.055, 0.075, 0.105, 1)


def _darkmat():
    return bs.M("txt_dark", DARK, rough=0.42, metallic=0.0)


def face_text(name, body, loc, size=0.6, dark=True, color=WHITE, strength=2.4, parent=None, appear=None):
    """立在 XZ 平面、正面朝相机（-Y）的字。dark=True 给亮面用。"""
    t = L.text(name, body, loc, size, color, strength, align="CENTER")
    t.rotation_euler = (math.pi / 2, 0, 0)
    if dark:
        t.data.materials.clear()
        t.data.materials.append(_darkmat())
    if parent is not None:
        bpy.context.view_layer.update()          # 没更新过 matrix_world 会拿到旧矩阵，字会跑位
        t.parent = parent
        t.matrix_parent_inverse = parent.matrix_world.inverted()
    if appear is not None:
        L.pop(t, appear)
    return t


def flat_text(name, body, loc, size=0.6, dark=False, color=WHITE, strength=2.4, appear=None, rot=0.0):
    """平躺在地面上的字（俯拍镜头用）。"""
    t = L.text(name, body, loc, size, color, strength, align="CENTER")
    t.rotation_euler = (0, 0, rot)
    if dark:
        t.data.materials.clear()
        t.data.materials.append(_darkmat())
    if appear is not None:
        L.pop(t, appear)
    return t


def plate(name, loc, w, d=0.6):
    return L.box(name, (w, d, 0.12), loc, bs.M("plate", PLATE, rough=0.6, metallic=0.3))


def column(name, x, h, f_grow, color=CYAN, glow=1.2, w=2.4, label=None, value=None,
           lab_size=0.52, val_size=0.66, z0=0.0, grow=26, dim=False):
    """一根会长高的柱子：名字刻在柱身上（深色），数值跟到柱顶（亮色）。

    h 是最终高度；f_grow 是开始长的帧。dim=True 是配角（灰、不发光）。
    """
    c = GREY if dim else color
    m = bs.M("col_dim", (0.085, 0.105, 0.14, 1), metallic=0.35, rough=0.55) if dim else bs.m_glow("col_" + name, c, glow)
    # ⛔ 起手高度不能是 0.015（等于一张贴在地上的片子）。柱子往往在镜头 40%~60% 处才开始长，
    #    前面那几秒画面就是空的——一个 10 秒的镜头开头三秒什么都没有，看着就是「画面空」。
    #    起手给 0.16：地上已经有一排矮墩，长起来仍然是清清楚楚的一次变化。
    z1 = 0.16
    o = L.box(name, (w, w * 0.82, max(h, 1e-3)), (x, 0, z0 + h / 2), m, bevel=0.03)
    bs.key_rel(o, 1, (1, 1, z1)); L.key_loc(o, 1, (x, 0, z0 + h * z1 / 2))
    bs.key_rel(o, f_grow, (1, 1, z1)); L.key_loc(o, f_grow, (x, 0, z0 + h * z1 / 2))
    bs.key_rel(o, f_grow + grow, (1, 1, 1)); L.key_loc(o, f_grow + grow, (x, 0, z0 + h / 2))
    y = -w * 0.41 - 0.03
    if label:
        face_text(name + "_lb", label, (x, y, z0 + 0.75), lab_size, dark=not dim,
                  color=WHITE if dim else WHITE, parent=None, appear=f_grow + grow - 6)
    if value:
        face_text(name + "_v", value, (x, y, z0 + h + 0.72), val_size, dark=False,
                  color=WHITE if dim else c, strength=3.0, appear=f_grow + grow)
    return o


def rail(name, x0, x1, z=0.0, r=0.09):
    """时间轴的横杆。"""
    L.box(name, (x1 - x0, 0.16, 0.16), ((x0 + x1) / 2, 0, z), bs.M("rail", (0.10, 0.14, 0.19, 1), metallic=0.5, rough=0.4))


def milestone(name, x, f, year, body, color=CYAN, h=2.6, z=0.0, size=0.62, sub=0.46, down=False, w=3.4):
    """时间轴上的一个节点：立起来的牌子 + 年份（刻在牌子上，深色）+ 一句说明。

    ⛔ 牌子必须比年份字宽，否则深色字会落到深色背景上，一个字都看不见。
    """
    pole = L.box(name, (w, 0.5, h), (x, 0, z + (-h / 2 if down else h / 2)), bs.m_glow("ms_" + name, color, 1.5), bevel=0.03)
    bs.key_rel(pole, 1, (1, 1, 0.01)); bs.key_rel(pole, f, (1, 1, 0.01)); bs.key_rel(pole, f + 16, (1, 1, 1))
    L.key_loc(pole, 1, (x, 0, z)); L.key_loc(pole, f, (x, 0, z))
    L.key_loc(pole, f + 16, (x, 0, z + (-h / 2 if down else h / 2)))
    face_text(name + "_y", year, (x, -0.29, z + (-h * 0.62 if down else h * 0.52)), size, dark=True, appear=f + 14)
    face_text(name + "_t", body, (x, -0.29, z + (-h - 0.9 if down else h + 0.9)), sub, dark=False, color=color, appear=f + 18)
    return pole


def cross(name, loc, size=1.5, color=ORANGE, f=1):
    """打叉（否掉一个说法）。"""
    for k, r in enumerate((0.7, -0.7)):
        o = L.box("%s_%d" % (name, k), (size * 1.6, 0.16, 0.16), loc, bs.m_glow("x_" + name, color, 3.0), rot=(0, r, 0))
        bs.key_rel(o, 1, (0.01, 1, 1)); bs.key_rel(o, f + k * 5, (0.01, 1, 1)); bs.key_rel(o, f + k * 5 + 9, (1, 1, 1))


def slab(name, loc, w, d, h=0.35, color=None, glow=0.0):
    m = bs.m_glow("slab_" + name, color, glow) if color and glow else bs.m_si()
    return L.box(name, (w, d, h), loc, m, bevel=0.02)


def cam_front(dist=26, height=9, target=(0, 0, 4), lens=42):
    return L.camera((target[0], -dist, height), target, lens=lens, fstop=5.0, focus=dist)
