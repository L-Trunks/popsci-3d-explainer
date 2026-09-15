# -*- coding: utf-8 -*-
"""封面：Blender 渲的 HBM 楼当底 + 科技感 HUD 层。python cover.py <底图> <out.png>"""
import sys
from PIL import Image, ImageDraw, ImageFont, ImageEnhance, ImageFilter

import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as C  # noqa: E402

W, H = C.CANVAS
FB = C.FONT_UI
SS = C.get("fonts.display") or FB      # 标题用的展示字体（如 SmileySans），没有就退回 UI 字体
MONO = C.FONT_MONO
AC = (58, 230, 255); OR = (255, 150, 40); TXT = (240, 246, 252); DIM = (120, 150, 175)

bg = Image.open(sys.argv[1]).convert("RGB").resize((W, H))

# 左上压暗，给标题让位；整体轻微降亮
bg = ImageEnhance.Brightness(bg).enhance(0.92)
vig = Image.new("L", (W, H), 0)
vd = ImageDraw.Draw(vig)
for i in range(160):
    vd.ellipse([-900 + i * 4, -700 + i * 3, 1250 - i * 2, 900 - i * 2], fill=min(255, int(i * 2.6)))
bg = Image.composite(Image.new("RGB", (W, H), (4, 7, 12)), bg, vig.filter(ImageFilter.GaussianBlur(60)))

# 扫描线
sl = Image.new("RGB", (W, H), (0, 0, 0)); sd = ImageDraw.Draw(sl)
for y in range(0, H, 3):
    sd.line([(0, y), (W, y)], fill=(14, 20, 28))
bg = Image.blend(bg, Image.blend(bg, sl, 0.35), 0.5)

d = ImageDraw.Draw(bg, "RGBA")

# 四角取景框
def bracket(x, y, sx, sy, L=70, w=5):
    d.line([(x, y), (x + sx * L, y)], fill=AC, width=w)
    d.line([(x, y), (x, y + sy * L)], fill=AC, width=w)
for (x, y, sx, sy) in ((54, 54, 1, 1), (W - 54, 54, -1, 1), (54, H - 54, 1, -1), (W - 54, H - 54, -1, -1)):
    bracket(x, y, sx, sy)

# 文案全部来自 config.json 的 cover 段（⛔ 主标题两行、每行 ≤6 字，超了会撞到右边的建模）
CV = C.get("cover", {}) or {}
SIGN = CV.get("sign", "")
EP = CV.get("ep", "")
fmono = ImageFont.truetype(MONO, 26)
d.text((150, 62), CV.get("slug", C.TITLE), font=fmono, fill=DIM)
fcjk = ImageFont.truetype(FB, 26)
if SIGN:
    d.text((W - 150 - fcjk.getlength(SIGN), 62), SIGN, font=fcjk, fill=DIM)
if EP:
    d.text((W - 168 - fcjk.getlength(SIGN) - fmono.getlength(EP), 62), EP, font=fmono, fill=DIM)

# 眉标
f3 = ImageFont.truetype(FB, 38)
d.rectangle([110, 168, 470, 176], fill=AC)
d.text((110, 196), CV.get("badge", ""), font=f3, fill=AC)

# 主标题（两行，第二行用强调色）
f1 = ImageFont.truetype(SS, 158)
t1 = CV.get("title", [C.TITLE, ""])
d.text((104, 276), t1[0], font=f1, fill=TXT, stroke_width=5, stroke_fill=(0, 0, 0))
if len(t1) > 1:
    d.text((104, 438), t1[1], font=f1, fill=OR, stroke_width=5, stroke_fill=(0, 0, 0))

# 副标题
f2 = ImageFont.truetype(SS, 62)
for i, s in enumerate(CV.get("sub", [])[:2]):
    d.text((110, 626 + i * 74), s, font=f2, fill=TXT, stroke_width=3, stroke_fill=(0, 0, 0))

# 数据条：三个「一眼看懂差距」的数字
items = [tuple(x) for x in CV.get("stats", [])]
if items:
    d.rounded_rectangle([104, 820, 960, 936], 10, fill=(8, 16, 24, 205), outline=(30, 62, 88), width=2)
fk = ImageFont.truetype(FB, 46); fv = ImageFont.truetype(MONO, 27)
fvc = ImageFont.truetype(FB, 27)
x = 148
for i, (k, u, nm) in enumerate(items):
    col = OR if i == len(items) - 1 else AC        # 最后一个用强调色：反差就在它身上
    d.text((x, 838), k, font=fk, fill=col)
    d.text((x, 892), u, font=fv, fill=DIM)
    d.text((x + fv.getlength(u) + 10, 891), nm, font=fvc, fill=DIM)
    x += 286
    if i < len(items) - 1:
        d.line([(x - 44, 846), (x - 44, 912)], fill=(30, 62, 88), width=2)

bg.save(sys.argv[2])
print("cover", sys.argv[2])
