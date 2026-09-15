# -*- coding: utf-8 -*-
"""深色 PIL 卡片（和 Blender 场景同一套配色）。python cards.py cards.json outdir

card 类型：
  {"id","type":"title","title","sub"}
  {"id","type":"number","big","unit","caption"}
  {"id","type":"table","title","head":[...],"rows":[[...],...],"hl":行号列表}
  {"id","type":"bullets","title","items":[...]}
*词* 高亮为青色。
"""
import json, sys, os
from PIL import Image, ImageDraw, ImageFont

W, H = 1920, 1080
BG = (9, 14, 22); TXT = (238, 244, 250); MUTED = (150, 170, 190); AC = (58, 230, 255); OR = (255, 140, 26); LINE = (28, 44, 62)
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import config as _C
FB = _C.FONT_UI; FR = _C.get("fonts.ui_regular", "C:/Windows/Fonts/msyh.ttc")


def F(sz, bold=True):
    return ImageFont.truetype(FB if bold else FR, sz)


def base():
    im = Image.new("RGB", (W, H), BG); d = ImageDraw.Draw(im)
    for x in range(0, W, 96):
        d.line([(x, 0), (x, H)], fill=(12, 19, 29))
    for y in range(0, H, 96):
        d.line([(0, y), (W, y)], fill=(12, 19, 29))
    d.rectangle([0, 0, W, 6], fill=(20, 40, 60))
    d.rectangle([80, 6, 380, 10], fill=AC)
    return im, d


def draw_emph(d, xy, text, font, fill=TXT, center=False):
    parts = text.split("*"); x, y = xy
    total = sum(font.getlength(p) for p in parts)
    if center:
        x = xy[0] - total / 2
    for i, p in enumerate(parts):
        d.text((x, y), p, font=font, fill=AC if i % 2 else fill)
        x += font.getlength(p)


def card_title(c):
    im, d = base()
    f = F(96); f2 = F(44, False)
    draw_emph(d, (W / 2, H * 0.36), c["title"], f, center=True)
    if c.get("sub"):
        draw_emph(d, (W / 2, H * 0.36 + 150), c["sub"], f2, MUTED, center=True)
    d.rectangle([W / 2 - 160, H * 0.36 + 125, W / 2 + 160, H * 0.36 + 131], fill=AC)
    return im


def card_number(c):
    im, d = base()
    f = F(220); fu = F(72); fc = F(46, False)
    big = c["big"]; unit = c.get("unit", "")
    tw = f.getlength(big) + (fu.getlength(unit) + 20 if unit else 0)
    x = (W - tw) / 2; y = H * 0.30
    d.text((x, y), big, font=f, fill=AC)
    if unit:
        d.text((x + f.getlength(big) + 20, y + 130), unit, font=fu, fill=TXT)
    if c.get("caption"):
        draw_emph(d, (W / 2, y + 300), c["caption"], fc, MUTED, center=True)
    return im


def card_table(c):
    im, d = base()
    ft = F(56); fh = F(40); fr = F(44, False)
    if c.get("title"):
        draw_emph(d, (W / 2, 90), c["title"], ft, center=True)
    head, rows = c["head"], c["rows"]; n = len(head)
    x0, x1 = 160, W - 160; cw = (x1 - x0) / n
    y = 240; rh = 96
    for j, h in enumerate(head):
        d.text((x0 + cw * j + cw / 2 - fh.getlength(h) / 2, y), h, font=fh, fill=AC)
    y += 70; d.line([(x0, y), (x1, y)], fill=AC, width=3); y += 16
    hl = set(c.get("hl", []))
    for i, r in enumerate(rows):
        if i in hl:
            d.rectangle([x0, y - 6, x1, y + rh - 14], fill=(20, 40, 60))
        for j, v in enumerate(r):
            col = OR if (i in hl and j == 0) else TXT
            draw_emph(d, (x0 + cw * j + cw / 2, y + 18), str(v), fr, col, center=True)
        y += rh; d.line([(x0, y - 8), (x1, y - 8)], fill=LINE, width=2)
    if c.get("foot"):
        draw_emph(d, (W / 2, H - 120), c["foot"], F(38, False), MUTED, center=True)
    return im


def card_bullets(c):
    im, d = base()
    ft = F(60); fi = F(46, False)
    if c.get("title"):
        draw_emph(d, (W / 2, 110), c["title"], ft, center=True)
    y = 300
    for it in c["items"]:
        d.rectangle([200, y + 22, 214, y + 36], fill=AC)
        draw_emph(d, (250, y), it, fi)
        y += 110
    return im


TYPES = dict(title=card_title, number=card_number, table=card_table, bullets=card_bullets)

if __name__ == "__main__":
    cards = json.load(open(sys.argv[1], encoding="utf-8")); out = sys.argv[2]
    os.makedirs(out, exist_ok=True)
    for c in cards:
        TYPES[c["type"]](c).save(os.path.join(out, c["id"] + ".png"))
        print("card", c["id"])
