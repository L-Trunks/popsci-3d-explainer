# -*- coding: utf-8 -*-
"""cards.py 的扩展：数据图（`{"type": "chart2", "kind": ...}`）。

    python cards2.py cards.json outdir

下面七个 kind 用的是**占位示例数据**（产品 A/B、公司 A/B/C），换题材时照着写自己的：
  price 双折线 / bw 三柱对比 / ups 百分比三柱 / timeline 时间轴 /
  share 份额饼 / share2 份额饼（少片版）/ chain 三栏链路图

⭐ 但更该做的是**把它们改成 3D 图表**（`bl_charts.py`）：会长高的柱子、跟着倒的名字、
   长出来的数值。纯文本画面占全片的比例是硬指标——第一版 18.6% 被判「像 PPT」，
   压到 5.0% 才过。卡片只留给大数字、对照表、片尾署名。
"""
import json, math, os, sys
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cards as C
from cards import W, H, BG, TXT, MUTED, AC, OR, LINE, F, base, draw_emph

GREEN = (80, 220, 140)
REDC = (255, 96, 88)
YEL = (255, 210, 70)


def _title(d, t, sub=None):
    draw_emph(d, (W / 2, 74), t, F(62), center=True)
    if sub:
        draw_emph(d, (W / 2, 156), sub, F(36, False), MUTED, center=True)


def chart_price(c):
    im, d = base()
    _title(d, "一年，涨成这样", "月度价格 · 示例数据")
    x0, x1, y0, y1 = 240, W - 200, 296, H - 336   # ⛔ 横轴标签在 y1+26，H-290 会让它落到 78%，收到 H-336
    for i in range(5):
        y = y1 - (y1 - y0) * i / 4
        d.line([(x0, y), (x1, y)], fill=LINE, width=2)
        d.text((x0 - 130, y - 22), ["0", "1000", "2000", "3000", "4000"][i], font=F(32, False), fill=MUTED)
    a = [800, 860, 980, 1250, 1700, 2400, 3100, 3800, 3750, 3820]
    b = [410, 430, 470, 540, 640, 760, 880, 950, 930, 950]
    labs = ["第 1 月", "", "", "", "", "", "", "第 8 月", "", "第 10 月"]
    def pts(v):
        return [(x0 + (x1 - x0) * i / (len(v) - 1), y1 - (y1 - y0) * min(val, 4000) / 4000) for i, val in enumerate(v)]
    for v, col, w in ((a, AC, 9), (b, OR, 9)):
        p = pts(v)
        d.line(p, fill=col, width=w, joint="curve")
        for q in p:
            d.ellipse([q[0] - 7, q[1] - 7, q[0] + 7, q[1] + 7], fill=col)
    p = pts(a)
    d.text((p[-1][0] - 300, p[-1][1] - 96), "产品 A  800 → 3800", font=F(42), fill=AC)
    q = pts(b)
    d.text((q[-1][0] - 300, q[-1][1] + 34), "产品 B  410 → 950", font=F(42), fill=OR)
    for i, t in enumerate(labs):
        if t:
            d.text((x0 + (x1 - x0) * i / (len(labs) - 1) - 60, y1 + 26), t, font=F(30, False), fill=MUTED)
    return im


def _bars(c, title, sub, items, unit, maxv=None, foot=None):
    """items: [(名字, 值, 颜色, 备注)]"""
    im, d = base()
    _title(d, title, sub)
    n = len(items)
    x0, x1, yb, yt = 260, W - 260, H - 420, 300   # ⛔ 底部 22.5% 留给字幕，柱底不能再低
    bw = (x1 - x0) / (n * 2 - 1)
    mx = maxv or max(v for _, v, _, _ in items)
    for i, (nm, v, col, note) in enumerate(items):
        x = x0 + i * bw * 2
        h = (yb - yt) * (v / mx)
        d.rectangle([x, yb - h, x + bw, yb], fill=col)
        d.rectangle([x, yb - h, x + bw, yb - h + 8], fill=(255, 255, 255))
        txt = ("%g" % v) + unit
        f = F(56)
        d.text((x + bw / 2 - f.getlength(txt) / 2, yb - h - 76), txt, font=f, fill=col)
        f2 = F(40, False)
        d.text((x + bw / 2 - f2.getlength(nm) / 2, yb + 24), nm, font=f2, fill=TXT)
        if note:
            f3 = F(30, False)
            d.text((x + bw / 2 - f3.getlength(note) / 2, yb + 72), note, font=f3, fill=MUTED)
    d.line([(x0 - 40, yb), (x1 + 40, yb)], fill=LINE, width=3)
    if foot:
        draw_emph(d, (W / 2, 782), foot, F(38, False), MUTED, center=True)   # ⛔ 830 会伸进字幕带（实测最低一行在 81%），收到 782
    return im


def chart_bw(c):
    return _bars(c, "同一台电脑，搬数的三条路", "本机实测 · GB/秒（示例）",
                 [("通道 A", 30, AC, "说明文字"),
                  ("通道 B", 405, GREEN, "说明文字"),
                  ("通道 C", 18, OR, "说明文字")],
                 " GB/s", foot="卡脖子的不是算，是*搬*")


def chart_ups(c):
    return _bars(c, "三类产品，涨幅差多少", "季度合同价涨幅 · 示例数据",
                 [("产品 A", 50, OR, "说明文字"),
                  ("产品 B", 40, AC, "说明文字"),
                  ("产品 C", 15, GREEN, "说明文字")],
                 "%", maxv=60, foot="用 *星号* 包住的词会被高亮")


def chart_timeline(c):
    im, d = base()
    _title(d, "五十年，只剩三家", None)
    y = 560
    d.line([(150, y), (W - 150, y)], fill=(40, 66, 92), width=6)
    ev = [(1970, "第一代产品上市\n两行说明", AC, -1),
          (1983, "后来者入场", OR, 1),
          (1985, "公司 A 退出", MUTED, -1),
          (1986, "某地区占 65%", OR, 1),
          (2009, "公司 B 倒闭", REDC, -1),
          (2012, "公司 C 倒闭\n公司 D 被收购", REDC, 1),
          (2016, "新玩家成立", GREEN, -1)]
    x0, x1 = 230, W - 230
    for i, (yr, txt, col, side) in enumerate(ev):
        x = x0 + (x1 - x0) * i / (len(ev) - 1)
        d.ellipse([x - 13, y - 13, x + 13, y + 13], fill=col)
        d.line([(x, y), (x, y + side * 52)], fill=col, width=4)
        fy = F(52)
        d.text((x - fy.getlength(str(yr)) / 2, y + (-118 if side < 0 else 66)), str(yr), font=fy, fill=col)
        f2 = F(30, False)
        for k, ln in enumerate(txt.split("\n")):
            yy = y + (-186 - (len(txt.split("\n")) - 1 - k) * 40 if side < 0 else 132 + k * 40)
            d.text((x - f2.getlength(ln) / 2, yy), ln, font=f2, fill=MUTED)
    return im


def _pie(d, cx, cy, r, parts, start=-90):
    a = start
    for nm, v, col in parts:
        sw = 360 * v / sum(p[1] for p in parts)
        d.pieslice([cx - r, cy - r, cx + r, cy + r], a, a + sw, fill=col, outline=BG, width=6)
        mid = math.radians(a + sw / 2)
        f = F(40)
        lab = "%s %.0f%%" % (nm, v)
        # ⛔ 定距放标签会让长名字压到环上；按自身宽度往外推，
        #    小于 6% 的薄片再多推一截，否则相邻两个小片的标签会叠在一起。
        off = r + 60 + f.getlength(lab) / 2 * abs(math.cos(mid)) + (58 if v < 6 else 0)
        tx, ty = cx + off * math.cos(mid), cy + (r + 96 + (58 if v < 6 else 0)) * math.sin(mid)
        if v >= 3:            # 2% 的薄片不写标签：它一定挤在别的标签旁边，而且没信息量
            d.text((tx - f.getlength(lab) / 2, ty - 24), lab, font=f, fill=col)
        a += sw
    d.ellipse([cx - r * 0.42, cy - r * 0.42, cx + r * 0.42, cy + r * 0.42], fill=BG)


def chart_share(c):
    im, d = base()
    _title(d, "全球市场份额", "某季度 · 数据来源写在这里")
    _pie(d, W / 2, 536, 166, [("公司 A", 39.4, AC), ("公司 B", 24.9, GREEN), ("公司 C", 23.3, OR), ("其他", 12.4, MUTED)])
    draw_emph(d, (W / 2, 206), "三家分掉 *87%* · 其余加起来一成出头", F(34, False), MUTED, center=True)
    return im


def chart_share2(c):
    im, d = base()
    _title(d, "换一个细分市场，排名倒过来", "某季度营收份额 · 示例数据")
    _pie(d, W / 2, 536, 166, [("公司 B", 50, GREEN), ("公司 A", 33, AC), ("公司 C", 18, OR)])
    draw_emph(d, (W / 2, 206), "一句解释排名为什么倒过来", F(34, False), MUTED, center=True)
    return im


def chain_col(d, x, w, title, rows, col):
    d.rectangle([x, 250, x + w, 262], fill=col)
    f = F(48)
    d.text((x + w / 2 - f.getlength(title) / 2, 286), title, font=f, fill=col)
    y = 380
    fr = F(38, False); fn = F(28, False)
    for nm, note in rows:
        d.rounded_rectangle([x, y, x + w, y + 96], 10, fill=(16, 26, 38), outline=(30, 50, 70), width=2)
        d.text((x + 26, y + 14), nm, font=fr, fill=TXT)
        d.text((x + 26, y + 58), note, font=fn, fill=MUTED)
        y += 112
    return y


def chart_chain(c):
    im, d = base()
    # ⛔ 卡片上的措辞必须和口播同一套说法：口播改了词（比如「最短」→「差得最远」），这里跟着改。
    _title(d, "一条产业链的三段", "上游 · 中游 · 下游（示例）")
    w = 480
    xs = [110, 720, 1330]
    chain_col(d, xs[0], w, "上游 · 材料", [("公司 A", "一句说明 · 一个数字"), ("公司 B", "一句说明 · 一个数字")], AC)
    chain_col(d, xs[1], w, "中游 · 制造", [("公司 C", "一句说明 · 一个数字"), ("公司 D", "一句说明 · 一个数字"), ("公司 E", "一句说明 · 一个数字")], YEL)
    y = chain_col(d, xs[2], w, "下游 · 设备", [("公司 F", "一句说明 · 一个数字"), ("公司 G", "一句说明 · 一个数字"), ("公司 H", "一句说明 · 一个数字")], GREEN)
    for x in (xs[0] + w + 40, xs[1] + w + 40):
        d.polygon([(x, 520), (x + 46, 546), (x, 572)], fill=MUTED)
    d.rounded_rectangle([xs[2], y + 16, xs[2] + w, y + 108], 10, fill=(46, 16, 16), outline=REDC, width=3)
    d.text((xs[2] + 26, y + 30), "短板：写在这里", font=F(38), fill=REDC)
    d.text((xs[2] + 26, y + 74), "一句话解释为什么是短板", font=F(26, False), fill=MUTED)
    return im


KINDS = dict(price=chart_price, bw=chart_bw, timeline=chart_timeline, share=chart_share,
             share2=chart_share2, chain=chart_chain, ups=chart_ups)


def card_chart2(c):
    return KINDS[c["kind"]](c)


C.TYPES["chart2"] = card_chart2

if __name__ == "__main__":
    cards = json.load(open(sys.argv[1], encoding="utf-8")); out = sys.argv[2]
    os.makedirs(out, exist_ok=True)
    for c in cards:
        C.TYPES[c["type"]](c).save(os.path.join(out, c["id"] + ".png"))
        print("card", c["id"], c["type"], c.get("kind", ""))
