# -*- coding: utf-8 -*-
"""段落级配音 + 条级字幕（v3 样式：无边框、单行、淡底、按标点断句、超宽自动分条）。

    python subs.py blank     把 sub_h/*.png 换成全透明（clip 阶段不烧整段字幕）
    python subs.py burn      生成 .ass → libass 一次烧进 out/<outfile>_sub.mp4

时间：块时间用和 build_video.shot_segments 相同的算法（关键词字符位置 × 段时长），块内各条按字数比例分。
断句：先按 ，。！？；：、 切成单元，再贪心合并到不超过 MAX_W 像素（PIL 量宽），永远只显示一行。
"""
import json, os, sys, re, subprocess
from PIL import Image, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import config as C  # noqa: E402
import build_video as BV  # noqa: E402

FILM = os.path.join(HERE, "work", "film")

W, H = C.CANVAS
FONT_FILE = C.FONT_SUB_FILE            # 楷体粗一点，比黑体有人味
FONT_NAME = C.FONT_SUB_NAME            # ⛔ libass 按字体**内部名**匹配，不是文件名
FS = C.SUB_SIZE                        # ⛔ 42 号在手机上看不清，60 才够
BOLD = 1                               # 楷体没有粗体面，让 libass 合成加粗
MAX_W = 1000                           # 单行最大宽度（像素，1920 画布）≈ 16 个楷体字
BOX_ALPHA = "78"                       # 底色透明度（00 不透明 … FF 全透明）
MARGIN_V = 120                         # ⛔ 往上挪：贴底会挡住画面里 3D 标签的下沿
PUNCT = "，。！？；：、"


def _font():
    return ImageFont.truetype(FONT_FILE, FS)


def units(text):
    """按标点切成断句单元（标点跟在前一单元后）。"""
    out = []; buf = ""
    for ch in text:
        buf += ch
        if ch in PUNCT:
            out.append(buf); buf = ""
    if buf.strip():
        out.append(buf)
    return [u for u in out if u.strip()]


LATIN = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz%.·"

try:
    import jieba as _jieba
    _jieba.setLogLevel(60)
except Exception:                              # 没装分词就只保证不劈开数字/字母
    _jieba = None


def _wordcuts(u):
    """u 里落在词边界上的下刀位置；没有分词就返回 None（不加这层限制）。"""
    if _jieba is None:
        return None
    idx = [i for i, ch in enumerate(u) if ch != "*"]
    s = "".join(u[i] for i in idx)
    ok = {len(u)}; p = 0
    for w in _jieba.cut(s, HMM=True):
        ok.add(idx[p] if p < len(idx) else len(u)); p += len(w)
    return ok


def _cut_ok(u, i, wc=None):
    """能不能在 u[:i] / u[i:] 之间下刀。"""
    if i <= 0 or i >= len(u):
        return False
    if u[i] in PUNCT or u[i] == "*":          # ⛔ 标点不许当下一条的第一个字
        return False
    if u[i - 1] in LATIN and u[i] in LATIN:   # 不把 1024 / DDR5 / 99% 劈开
        return False
    if wc is not None and i not in wc:        # 不把「并排」「带宽」这种词劈开
        return False
    return True


def _split_unit(u, plain_w, maxw):
    """一个标点单元本身就超宽：切成几份**等长**的，切口尽量落在中间。

    ⛔ 0911 用户：断长句要断在中间，而且切剩的尾巴不许并进下一句
       （老写法贪心填到满、剩「0 和 1。」两三个字跑去跟下一句挤，字幕就会以标点开头）。
    """
    n = len(u); wc = _wordcuts(u)
    for constraint in (wc, None):              # 先只在词边界下刀，实在找不到再放宽
        for k in range(2, 12):
            if plain_w(u) / k > maxw * 0.98:
                continue
            cuts = []; prev = 0
            for j in range(1, k):
                t = int(round(n * j / k)); best = None
                for d in range(0, 9):
                    for i in (t - d, t + d):
                        if i > prev and _cut_ok(u, i, constraint):
                            best = i; break
                    if best:
                        break
                if best is None:
                    cuts = None; break
                cuts.append(best); prev = best
            if cuts is None:
                continue
            pieces = []; last = 0
            for c in cuts + [n]:
                pieces.append(u[last:c]); last = c
            if all(plain_w(p) <= maxw for p in pieces):
                return [p for p in pieces if p.strip()]
    return [u]


def cues_of(text, font):
    """整段 → 若干条字幕。完整标点单元可以合并；被拆开的长句自成一条，绝不跨句黏连。"""
    plain_w = lambda s: font.getlength(s.replace("*", ""))
    atoms = []                                    # (文本, 是否完整单元)
    for u in units(text):
        if plain_w(u) > MAX_W:
            ps = _split_unit(u, plain_w, MAX_W)
            atoms += [(p, len(ps) == 1) for p in ps]
        else:
            atoms.append((u, True))
    cues = []
    for s, whole in atoms:
        # 只有「两边都是完整句子」才允许并成一条，被拆开的碎片一律单独成条
        if cues and whole and cues[-1][1] and plain_w(cues[-1][0] + s) <= MAX_W:
            cues[-1] = (cues[-1][0] + s, True)
        else:
            cues.append((s, whole))
    cues = [c for c, _ in cues]
    # 收尾：太短的尾条（≤4 字）并回前一条（不超宽才并）
    if len(cues) >= 2 and len(cues[-1].replace("*", "").strip(PUNCT)) <= 4 and plain_w(cues[-2] + cues[-1]) <= MAX_W:
        cues[-2] += cues[-1]; cues.pop()
    # 保险：任何一条都不许以标点开头，开头的标点退回上一条
    for i in range(1, len(cues)):
        while cues[i] and cues[i][0] in PUNCT:
            cues[i - 1] += cues[i][0]; cues[i] = cues[i][1:]
    return [c for c in cues if c.strip()]


def ass_text(s):
    """*词* → 青色高亮；去掉行尾句号/逗号让画面干净。"""
    s = s.strip()
    while s and s[-1] in "，。；：、":
        s = s[:-1]
    parts = s.split("*"); out = ""
    for i, p in enumerate(parts):
        p = p.replace("{", "").replace("}", "")
        out += ("{\\c&HFFE63A&}%s{\\c&HFAF4EE&}" % p) if i % 2 else p
    return out


def ts(t):
    h = int(t // 3600); m = int(t % 3600 // 60); s = t % 60
    return "%d:%02d:%05.2f" % (h, m, s)


def strip_ovr(nar):
    return re.sub(r"\{\{([^|{}]*)\|[^|{}]*\}\}", r"\1", nar)


WM_TEXT = C.WATERMARK                  # 空字符串 = 不打水印
WM_PERIOD = 30.0                       # 每 30 秒换一次位置
WM_FLY = 1.1                           # 飞入耗时（秒）
WM_HI = (1556, 176)                    # 斜上方那个落点
WM_LO = (1702, 902)                    # 斜下方那个落点


def watermark(total):
    """防搬运水印：每 30 秒从一个落点飘到另一个落点停住，下一段再飘回来。

    两个落点轮流坐庄：偶数段 上→下、奇数段 下→上，**上一段停在哪儿、下一段就从哪儿起飞**，
    位置连续，不会闪现。

    ⛔ 两个落点都得避开已经有东西的地方，否则等于给自己的画面打码：
       · 字幕 Sub 居中、MarginL/R 60、单行最宽 1000 px → 横向占 x 460~1460，所以 x 取 1556+；
       · 章节进度条在 y 1044~1080，HUD 在左上角 → 下落点 y 取 902（字幕上沿之上、进度条之上）；
       · 上落点 y 176，避开顶部章节卡（Card 的 MarginV 300）。
    ⛔ 半透明 + 描边两件都要：只降不透明度，压到亮画面上就糊了；只描边，压到暗画面上又太跳。
    """
    out = []
    if not WM_TEXT:
        return out
    n = int(total // WM_PERIOD) + 1
    for i in range(n):
        t0 = i * WM_PERIOD
        t1 = min(t0 + WM_PERIOD, total)
        if t1 - t0 < 1.5:
            break
        a, b = (WM_HI, WM_LO) if i % 2 == 0 else (WM_LO, WM_HI)
        out.append("Dialogue: 8,%s,%s,Mark,,0,0,0,,{\\move(%d,%d,%d,%d,0,%d)\\fad(350,300)}%s"
                   % (ts(t0), ts(t1), a[0], a[1], b[0], b[1], int(WM_FLY * 1000), WM_TEXT))
    return out


def ass():
    """字幕 + 章节卡 + HUD + 章节进度条 + 水印 → work/film/subs.ass（只生成文件，不编码）。"""
    cfg = json.load(open(os.path.join(FILM, "storyboard.json"), encoding="utf-8"))
    durs = json.load(open(os.path.join(FILM, "_durs.json")))
    cdir = os.path.join(FILM, "clips_h"); odir = os.path.join(FILM, "out")
    src = os.path.join(odir, cfg["outfile"] + ".mp4")
    font = _font(); t0 = 0.0; lines = []; T = float(cfg.get("transition", 0) or 0)
    ap = os.path.join(FILM, "align.json")
    align = json.load(open(ap, encoding="utf-8")) if os.path.exists(ap) else {}
    MIN_D = 0.9                      # 一条字幕最短停留
    for si, s in enumerate(cfg["scenes"]):
        clip = BV.probe_dur(os.path.join(cdir, s["id"] + ".mp4"))
        if si:
            t0 -= T          # xfade 每个接缝吃掉 T 秒
        D = BV.scene_dur(cfg, s, durs)
        nar = strip_ovr(s["narration"]); plain = nar.replace("*", "")
        a = align.get(s["id"])
        if a and a["disp"] == plain:
            # 逐字时间：整段一次断句，每条按首末字的 whisper 时间定
            cs = cues_of(nar, font); base = t0 + cfg.get("head_pad", 0.1); off = 0; spans = []
            for c in cs:
                n = len(c.replace("*", "")); i0, i1 = off, off + n - 1
                while i1 > i0 and (plain[i1] in PUNCT or plain[i1].isspace()):
                    i1 -= 1
                spans.append((base + a["t"][i0][0], base + a["t"][i1][1] + 0.12)); off += n
            for k, (c, (st, en)) in enumerate(zip(cs, spans)):
                nxt = spans[k + 1][0] if k + 1 < len(spans) else t0 + clip - 0.05
                en = min(max(en, st + MIN_D), nxt - 0.04)
                lines.append("Dialogue: 0,%s,%s,Sub,,0,0,0,,%s" % (ts(st), ts(en), ass_text(c)))
            t0 += clip; continue
        print("!! 无逐字对齐，退回字数比例：", s["id"])
        shots = s.get("shots") or [{"at": plain[:4]}]
        segs = BV.shot_segments(shots, plain, D)
        pos = []
        for sh in shots:
            p = plain.find(sh["at"], (pos[-1] + 1) if pos else 0); pos.append(p if p >= 0 else (pos[-1] if pos else 0))
        pos[0] = 0; pos.append(len(plain))
        raw_i = 0; t = t0 + cfg.get("head_pad", 0.1)
        for k in range(len(shots)):
            n_chars = pos[k + 1] - pos[k]; buf = ""; j = 0
            while raw_i < len(nar) and j < n_chars:
                if nar[raw_i] == "*":
                    buf += "*"; raw_i += 1; continue
                buf += nar[raw_i]; raw_i += 1; j += 1
            while raw_i < len(nar) and nar[raw_i] == "*":
                buf += "*"; raw_i += 1
            if buf.count("*") % 2:
                buf = buf.replace("*", "")
            cs = cues_of(buf, font); total = sum(len(c.replace("*", "")) for c in cs) or 1
            tt = t
            for c in cs:
                d = segs[k] * len(c.replace("*", "")) / total
                lines.append("Dialogue: 0,%s,%s,Sub,,0,0,0,,%s" % (ts(tt), ts(tt + d - 0.04), ass_text(c)))
                tt += d
            t += segs[k]
        t0 += clip
    # ---- 结构件（skill beat-driven-explainer §4）：章节卡（章首 1.6 s）+ 顶部 HUD（章 › 小节）
    #      + 底部章节进度条。三件一起做，片子才有「知道自己看到哪儿了」的长片感。
    # 章节表写在 chapters.py 里（片子内容，不是引擎）：
    #      CH  = [(章名, [段id, ...]), ...]    章名 ≤6 字
    #      SEC = {段id: 小节名}
    # ⛔ 改稿重排段落顺序 / 拆段之后**章节表必须跟着改**。少写一段会在 SEC[sid] 直接 KeyError，
    #    而且是卡在 final_pass 最后一步——前面几十分钟的活白干。下面这道 assert 提前报。
    try:
        from chapters import CH, SEC
    except ImportError:       # 没写章节表就退化成「一段一章」，片子照样能出，只是导航粗
        CH = [(s["id"], [s["id"]]) for s in cfg["scenes"]]
        SEC = {s["id"]: s["id"] for s in cfg["scenes"]}
    _miss = [s["id"] for s in cfg["scenes"] if s["id"] not in SEC]
    assert not _miss, "chapters.py 的章节表漏了这几段：%s" % _miss
    _mis2 = [i for _, ids in CH for i in ids if i not in SEC]
    assert not _mis2, "CH 里出现了 SEC 没有的段：%s" % _mis2
    st = {}; tt0 = 0.0
    for si, s in enumerate(cfg["scenes"]):
        clip = BV.probe_dur(os.path.join(cdir, s["id"] + ".mp4"))
        if si:
            tt0 -= T
        st[s["id"]] = (tt0, tt0 + clip); tt0 += clip
    total = tt0
    extra = []
    # ── 底部章节进度条 ──────────────────────────────────────────────────────
    # ⛔⛔ 0912 用户第 1 条：「底部的章节显示是可以模拟进度条的，随着视频播放，
    #    高亮部分也向前走。」旧写法是**整章一起高亮**——一章从头到尾都是同一个亮块，
    #    播到章中间完全看不出走了多远。新写法：一条底带到底，上面压一条**按秒推进**
    #    的填充 + 一个游标，章名和分隔线照旧。
    # ⛔ 为什么不用 `\t` 动画 `\clip`：libass 的动画裁剪要看版本，静默失败的话整条进度条
    #    要么全亮要么不亮，而且渲完才看得见。改成**离散步进**，每秒一格，
    #    1920 px ÷ 总秒数 ≈ 1.8 px/格，肉眼已经是连续的，零风险。
    # ⛔ 每格只活它自己那一秒（start=ta, end=tb），不是「从 ta 活到片尾」——
    #    后者会让片尾同时叠着上千个绘图。
    BAR_T, BAR_B = H - 36, H
    extra.append("Dialogue: 0,%s,%s,Bar,,0,0,0,,{\\p1\\pos(0,0)\\1c&H120F0C&\\1a&H28&}m 0 %d l %d %d %d %d 0 %d{\\p0}"
                 % (ts(0), ts(total), BAR_T, W, BAR_T, W, BAR_B, BAR_B))
    k = 0
    while k < total:
        ta = float(k); tb = min(k + 1.0, total)
        x = max(2, int(W * tb / total))
        extra.append("Dialogue: 1,%s,%s,Bar,,0,0,0,,{\\p1\\pos(0,0)\\1c&H4A3A2A&\\1a&H10&}m 0 %d l %d %d %d %d 0 %d{\\p0}"
                     % (ts(ta), ts(tb), BAR_T + 2, x, BAR_T + 2, x, BAR_B, BAR_B))
        extra.append("Dialogue: 2,%s,%s,Bar,,0,0,0,,{\\p1\\pos(0,0)\\1c&HFFE63A&\\1a&H08&}m 0 %d l %d %d %d %d 0 %d{\\p0}"
                     % (ts(ta), ts(tb), BAR_B - 4, x, BAR_B - 4, x, BAR_B, BAR_B))
        extra.append("Dialogue: 3,%s,%s,Bar,,0,0,0,,{\\p1\\pos(0,0)\\1c&HFFFFFF&\\1a&H18&}m %d %d l %d %d %d %d %d %d{\\p0}"
                     % (ts(ta), ts(tb), x - 2, BAR_T, x + 1, BAR_T, x + 1, BAR_B, x - 2, BAR_B))
        k += 1
    for ci, (name, ids) in enumerate(CH):
        c0 = st[ids[0]][0]; c1 = st[ids[-1]][1]
        x0 = int(W * c0 / total); x1 = int(W * c1 / total); xc = (x0 + x1) // 2
        if ci:   # 章与章之间的分隔线，进度条从它下面走过去
            extra.append("Dialogue: 4,%s,%s,Bar,,0,0,0,,{\\p1\\pos(0,0)\\1c&H000000&\\1a&H38&}m %d %d l %d %d %d %d %d %d{\\p0}"
                         % (ts(0), ts(total), x0 - 1, BAR_T, x0 + 1, BAR_T, x0 + 1, BAR_B, x0 - 1, BAR_B))
        extra.append("Dialogue: 5,%s,%s,BarTxt,,0,0,0,,{\\pos(%d,%d)\\1c&H9A9A90&}%s" % (ts(0), ts(total), xc, H - 20, name))
        extra.append("Dialogue: 6,%s,%s,BarTxt,,0,0,0,,{\\pos(%d,%d)\\1c&HFFE63A&}%s" % (ts(c0), ts(c1), xc, H - 20, name))
        if ci:
            extra.append("Dialogue: 7,%s,%s,Card,,0,0,0,,{\\fad(250,350)}%s" % (ts(c0 + 0.05), ts(c0 + 1.7), name))
            extra.append("Dialogue: 7,%s,%s,CardSub,,0,0,0,,{\\fad(250,350)}第 %d 章" % (ts(c0 + 0.05), ts(c0 + 1.7), ci + 1))
        for sid in ids:
            a, b = st[sid]
            extra.append("Dialogue: 0,%s,%s,Hud,,0,0,0,,{\\fad(200,200)}%s  ›  %s" % (ts(a + (1.8 if ci and sid == ids[0] else 0.2)), ts(b - 0.1), name, SEC[sid]))
    extra += watermark(total)
    lines += extra
    hdr = """[Script Info]
ScriptType: v4.00+
PlayResX: %d
PlayResY: %d
WrapStyle: 2""" % (W, H) + """
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Sub,%s,%d,&H00FAF4EE,&H00FFFFFF,&H%s0A0E14,&H%s0A0E14,%d,0,0,0,100,100,1,0,3,6,0,2,60,60,%d,1
Style: Hud,%s,28,&H30FAF4EE,&H00FFFFFF,&H900A0E14,&H900A0E14,0,0,0,0,100,100,1,0,3,5,0,7,40,40,28,1
Style: Card,%s,110,&H00FAF4EE,&H00FFFFFF,&H600A0E14,&H600A0E14,1,0,0,0,100,100,2,0,3,18,0,8,60,60,300,1
Style: CardSub,%s,36,&H20FFE63A,&H00FFFFFF,&H600A0E14,&H600A0E14,0,0,0,0,100,100,2,0,3,10,0,8,60,60,250,1
Style: Bar,Arial,20,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1
Style: BarTxt,%s,24,&H00FAF4EE,&H00FFFFFF,&H00000000,&H00000000,1,0,0,0,100,100,0,0,1,0,0,5,0,0,0,1
Style: Mark,%s,36,&H66FAF4EE,&H00FFFFFF,&H8C0A0E14,&H8C0A0E14,1,0,0,0,100,100,2,0,1,2,0,5,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
""" % (FONT_NAME, FS, BOX_ALPHA, BOX_ALPHA, BOLD, MARGIN_V, FONT_NAME, FONT_NAME, FONT_NAME, FONT_NAME, FONT_NAME)
    ass = os.path.join(FILM, "subs.ass")
    open(ass, "w", encoding="utf-8-sig").write(hdr + "\n".join(lines) + "\n")
    print("subs.ass %d 条字幕，最长 %d 字" % (len(lines), max(len(re.sub(r"\{[^}]*\}", "", l.split(",,")[-1])) for l in lines)))
    return ass


def subs_filter():
    """返回可直接塞进 ffmpeg 滤镜串的 subtitles=... 片段（libass 吃不了中文路径：ass 和字体拷到 ASCII 临时目录）。"""
    import shutil, tempfile
    ass = os.path.join(FILM, "subs.ass")
    tmp = os.path.join(tempfile.gettempdir(), "popsci_subs"); os.makedirs(os.path.join(tmp, "fonts"), exist_ok=True)
    shutil.copy(ass, os.path.join(tmp, "subs.ass")); shutil.copy(FONT_FILE, os.path.join(tmp, "fonts", os.path.basename(FONT_FILE)))
    ass_f = os.path.join(tmp, "subs.ass").replace("\\", "/").replace(":", "\\:")
    fontsdir = os.path.join(tmp, "fonts").replace("\\", "/").replace(":", "\\:")
    return "subtitles='%s':fontsdir='%s'" % (ass_f, fontsdir)


def burn():
    """旧路径：单独烧一遍字幕出 _sub.mp4（整片重编码）。现在成片走 make.py final 一次过，这里留给单独检查字幕用。"""
    cfg = json.load(open(os.path.join(FILM, "storyboard.json"), encoding="utf-8"))
    odir = os.path.join(FILM, "out"); src = os.path.join(odir, cfg["outfile"] + ".mp4")
    ass(); final = os.path.join(odir, cfg["outfile"] + "_sub.mp4")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", src, "-vf", subs_filter(),
                    "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "copy", final], check=True)
    print("→", final)


def blank():
    sdir = os.path.join(FILM, "sub_h")
    for f in os.listdir(sdir):
        if f.endswith(".png"):
            Image.new("RGBA", (W, H), (0, 0, 0, 0)).save(os.path.join(sdir, f))
    print("blanked", len(os.listdir(sdir)))


if __name__ == "__main__":
    {"blank": blank, "burn": burn, "ass": ass}[sys.argv[1]]()
