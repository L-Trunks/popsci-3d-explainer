# -*- coding: utf-8 -*-
"""把真实命令行输出做成「终端打字」视频。python terminal.py spec.json out.mp4

spec: {"cmd": "smartctl -a /dev/sdb", "lines": [...输出行...], "hl": ["Percentage Used", ...], "dur": 12, "title": "我的 4TB 盘"}
命令逐字打出 → 回车 → 输出行按顺序刷出（每行 ~3 帧）→ 高亮行变青并放大注释。
"""
import json, sys, os, subprocess
from PIL import Image, ImageDraw, ImageFont

W, H, FPS = 1920, 1080, 30
BG = (12, 14, 18); PANEL = (18, 21, 27); TXT = (214, 220, 228); DIM = (120, 130, 145); AC = (58, 230, 255); GREEN = (120, 220, 120); OR = (255, 140, 26)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as C  # noqa: E402
MONO = C.FONT_MONO; CJK = C.FONT_UI


def render(spec, out):
    fm = ImageFont.truetype(MONO, 30); fc = ImageFont.truetype(CJK, 34); fbig = ImageFont.truetype(CJK, 40)
    cmd = spec["cmd"]; lines = spec["lines"]; hl = spec.get("hl", []); dur = float(spec.get("dur", 12))
    N = int(dur * FPS); type_f = int(1.4 * FPS)
    # ⛔ per_line 原来写死 2 帧：14 行结果 28 帧（不到 1 秒）就刷完，后面**整整 21 秒一动不动**。
    #    逐帧 QC 量到 p06 有 12.0 s 的静止段，根子就在这儿（成片里这一块占 14.7 s）。
    #    改成按片长摊开：留 1.4 s 打字 + 末尾 2 s 停住让人读完，中间匀给每一行。
    per_line = spec.get("per_line") or max(2, (N - type_f - 8 - int(2.0 * FPS)) // max(1, len(lines)))
    lh = 40; y0 = 150; x0 = 90
    notes = spec.get("notes", {})
    p = subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "%dx%d" % (W, H), "-r", str(FPS), "-i", "-",
                          "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", out], stdin=subprocess.PIPE)
    for i in range(N):
        im = Image.new("RGB", (W, H), BG); d = ImageDraw.Draw(im)
        d.rounded_rectangle([40, 40, W - 40, H - 40], radius=18, fill=PANEL, outline=(40, 46, 56), width=2)
        for k, col in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
            d.ellipse([70 + k * 34, 62, 92 + k * 34, 84], fill=col)
        if spec.get("title"):
            d.text((W - 80 - fc.getlength(spec["title"]), 58), spec["title"], font=fc, fill=DIM)
        shown = min(len(cmd), int(len(cmd) * min(1.0, i / type_f)) + (1 if i < type_f else 0))
        d.text((x0, y0), "PS C:\\> ", font=fm, fill=GREEN)
        d.text((x0 + fm.getlength("PS C:\\> "), y0), cmd[:shown], font=fm, fill=TXT)
        if i < type_f and (i // 8) % 2 == 0:
            cx = x0 + fm.getlength("PS C:\\> " + cmd[:shown]) + 4
            d.rectangle([cx, y0 + 4, cx + 14, y0 + 32], fill=TXT)
        if i > type_f + 8:
            nline = min(len(lines), (i - type_f - 8) // per_line)
            y = y0 + lh + 10
            for ln in lines[:nline]:
                is_hl = any(h in ln for h in hl)
                d.text((x0, y), ln, font=fm, fill=AC if is_hl else TXT)
                if is_hl and nline >= len(lines) and ln.split(":")[0].strip() in notes:
                    note = notes[ln.split(":")[0].strip()]
                    d.polygon([(x0 + 1000, y + 18), (x0 + 1026, y + 4), (x0 + 1026, y + 32)], fill=OR)
                    d.text((x0 + 1040, y - 4), note, font=fbig, fill=OR)
                y += lh
        p.stdin.write(im.tobytes())
    p.stdin.close(); p.wait()
    print("terminal", out, N, "frames")


if __name__ == "__main__":
    render(json.load(open(sys.argv[1], encoding="utf-8")), sys.argv[2])
