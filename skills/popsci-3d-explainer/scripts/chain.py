# -*- coding: utf-8 -*-
"""配音之后的一条龙。每步都打时间，失败即停。

    python chain.py tts       出配音（按 config.tts.backend，必须先有 storyboard.json）
    python chain.py audio     配音后处理 → 插停顿 → 逐字对齐 → beats
    python chain.py render    按 beats 全量渲染（最长的一步；chain.py render S11,S12 只重渲几镜）
    python chain.py cover     只出封面（bl_cover.py → cover.py → 成品/<片名>_封面.png）
    python chain.py post      encode → segs → real → cards → build → cover → final_pass
    python chain.py all       audio → render → post 连着跑

⛔ 顺序是**死的**：先出声音，再按声音的逐字时间轴渲画面。反过来做出来的动画一定对不上口播。
"""
import glob, json, os, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import config as C  # noqa: E402

FILM = os.path.join(HERE, "work", "film")
BL = os.path.join(HERE, "work", "blender")
PY = C.PY_AUDIO
BLENDER = C.BLENDER
T0 = time.time()


def step(msg):
    print("\n=== [%6.0fs] %s" % (time.time() - T0, msg), flush=True)


def run(cmd, **kw):
    print(">", " ".join(str(c) for c in cmd)[:170], flush=True)
    subprocess.run(cmd, check=True, **kw)


def mk(*a):
    run([PY, "-X", "utf8", os.path.join(HERE, "make.py"), *a])


def tts(only=None):
    """按 config.tts.backend 出配音 → work/film/tts/<段>.wav。

    ⛔ 必须先有 storyboard.json（`python make.py storyboard`）——TTS 读的是它，不是 scenes.py。
    ⛔ 改过稿就**先刷 storyboard 再配音**，否则配的还是旧词。
    """
    step("配音（%s）" % C.TTS_BACKEND)
    sb = os.path.join(FILM, "storyboard.json")
    assert os.path.exists(sb), "先跑 make.py storyboard"
    if C.TTS_BACKEND == "voxcpm":
        cmd = [C.TTS_PY, "-X", "utf8", C.TTS_SCRIPT, sb, "--tempo", "%.2f" % C.TTS_TEMPO]
    else:
        cmd = [PY, "-X", "utf8", os.path.join(HERE, "tts_edge.py"), sb]
    if only:
        cmd += ["--only", ",".join(only)]
    run(cmd)
    n = len(glob.glob(os.path.join(FILM, "tts", "*.wav")))
    m = len(json.load(open(sb, encoding="utf-8"))["scenes"])
    # ⛔ 每次配音之后必须数 wav 数 == 场景数。本地 TTS 抢不到显存时会**静默退出**，
    #    只留下前 N 条；云端 TTS 也会偶发丢句。缺的用 --only 补跑。
    assert n >= m, "配音只出了 %d 条，应有 %d 条（用 --only 补跑缺的那几段）" % (n, m)


def audio():
    step("配音后处理：tts → tts_raw，逐段对齐响度")
    raw = os.path.join(FILM, "tts_raw"); os.makedirs(raw, exist_ok=True)
    ids = []
    for f in sorted(glob.glob(os.path.join(FILM, "tts", "p*.wav"))):
        sid = os.path.splitext(os.path.basename(f))[0]
        dst = os.path.join(raw, sid + ".wav")
        # ⛔⛔ 不能按 mtime 同步：pauses.apply() 会改 tts/，于是第二次跑 audio() 时
        #    「已插过停顿」的音频被当成原始素材抄进 tts_raw，原始 VoxCPM 输出就没了。
        #    tts_raw 只在缺文件时建立，之后一律只读。
        if not os.path.exists(dst):
            import shutil
            shutil.copy2(f, dst)
        ids.append(sid)
    # ⛔ 段数必须对得上：拆段（p09 → p09/p09b/p09c）或让某段退出 SCENES（片尾改静默）之后
    #    最容易在这儿露馅——少一段不会报错，只会在总装时发现片子短了一截。
    import scenes as _sc
    assert len(ids) == len(_sc.SCENES), "配音 %d 段，稿 %d 段：%s" % (len(ids), len(_sc.SCENES), ids)
    mk("voice", ",".join(ids))
    step("逐字对齐（faster-whisper，用 config.py_audio 那个解释器）")
    # ⛔ align.py 跑完会在退出阶段崩（faster-whisper teardown，0xC0000409），但 align.json 已经写完。
    #    所以不看退出码，只看产物：13 段齐 + 每段 disp 和 storyboard 的口播逐字一致 + 末字止贴住时长。
    import re as _re
    ap = os.path.join(FILM, "align.json")
    todo = [s for s in json.load(open(os.path.join(FILM, "storyboard.json"), encoding="utf-8"))["scenes"]]
    old = json.load(open(ap, encoding="utf-8")) if os.path.exists(ap) else {}

    def _disp(n):
        return _re.sub(r"\{\{([^|{}]*)\|[^|{}]*\}\}", r"\1", n).replace("*", "")

    def _read(n):
        return _re.sub(r"\{\{[^|{}]*\|([^|{}]*)\}\}", r"\1", n).replace("*", "")

    # ⛔ 只比显示串不够：只改读音侧（{{长|涨}}、{{，|。}}）时显示串一个字没动，
    #    但 wav 变了，不重对齐字幕就会整段错位。0911 踩过。
    # ⛔⛔ 只比文本不够：插过停顿以后 wav 变长了而文本一个字没动，
    #    拿「有停顿那一版」的时间轴去给「没停顿的音频」定落点，会整段偏几秒。
    #    所以再比一次时长。
    def _wavdur(sid):
        import soundfile as _sf
        p = os.path.join(FILM, "tts", sid + ".wav")
        if not os.path.exists(p):
            return -1.0
        i = _sf.info(p)
        return i.frames / float(i.samplerate)

    stale = [s["id"] for s in todo if s["id"] not in old
             or old[s["id"]]["disp"] != _disp(s["narration"])
             or old[s["id"]].get("read") != _read(s["narration"])
             or abs(old[s["id"]].get("dur", 0.0) - _wavdur(s["id"])) > 0.25]
    def _align(who):
        print("对齐：", ",".join(who), flush=True)
        subprocess.run([PY, "-X", "utf8", os.path.join(HERE, "align.py"), "cuda", ",".join(who)])

    if stale:
        _align(stale)                       # 第一遍：拿到停顿落点需要的逐字时间
    step("在转折/换内容处插真停顿（make.py voice 每轮都从 tts_raw 重建，所以每轮都要重插）")
    # ⛔ 实测 VoxCPM 不按标点改停顿长度，靠改标点做不出语气变化，只能在波形上开口子。
    import pauses
    pauses.apply()
    step("量时长（必须在插完停顿之后）")
    mk("durs")
    step("插过停顿，全量重对齐——不重对齐字幕和拍点会整体错位")
    _align(ids)
    a = json.load(open(ap, encoding="utf-8"))
    bad = []
    for s in todo:
        k = s["id"]
        if k not in a or a[k]["disp"] != _disp(s["narration"]):
            bad.append(k + "(文本对不上)")
        elif len(a[k]["t"]) != len(a[k]["disp"]):
            bad.append(k + "(时间戳条数不对)")
        elif a[k]["t"][-1][1] < a[k]["dur"] - 2.0:
            bad.append(k + "(末字止离结尾差 %.1fs)" % (a[k]["dur"] - a[k]["t"][-1][1]))
    assert not bad, "对齐产物不合格：" + " ".join(bad)
    print("对齐验收通过：%d 段" % len(a), flush=True)
    step("把切点写进 storyboard，再出 beats")
    mk("storyboard")
    mk("beats")
    b = json.load(open(os.path.join(FILM, "beats.json"), encoding="utf-8"))
    tot = sum(v["N"] for v in b.values())
    print("beats %d 镜，共 %d 帧 ≈ %.1f 分钟画面" % (len(b), tot, tot / 30 / 60))


def render(only=None):
    step("渲染前闸门：磁盘空间 + 口播一致性 + 拍点词命中")
    print("空间还剩 %.1f GB" % C.assert_disk(), flush=True)
    for g in ("check_scenes.py", "check_beats_kw.py"):
        r = subprocess.run([PY, "-X", "utf8", os.path.join(HERE, g)], capture_output=True, text=True, errors="replace")
        print(r.stdout[-800:], flush=True)
        assert "_OK" in r.stdout, g + " 没过，先修再渲"
    step("渲染（beats 驱动）")
    b = json.load(open(os.path.join(FILM, "beats.json"), encoding="utf-8"))
    env = dict(os.environ, BEATS_JSON=os.path.join(FILM, "beats.json"))
    todo = sorted(b.keys(), key=lambda k: int(k[1:-1]))
    fails = []
    for seg in todo:
        shot = seg[:-1]
        if only and shot not in only:
            continue
        d = os.path.join(BL, shot)
        done = os.path.join(d, "done.txt")
        need = b[seg]["N"]
        if os.path.exists(done) and int(open(done).read().strip() or 0) >= need:
            print("skip", shot, flush=True); continue
        t = time.time()
        r = subprocess.run([BLENDER, "-b", "--python", C.SHOT_ENTRY, "--", shot, d],
                           capture_output=True, text=True, errors="replace", env=env)
        n = len(glob.glob(os.path.join(d, "*.png")))
        ok = "RENDER_DONE" in r.stdout and n >= need
        if ok:
            open(done, "w").write(str(n))
        print("%-5s %s frames=%d/%d  %.0fs" % (shot, "ok " if ok else "FAIL", n, need, time.time() - t), flush=True)
        # 标签体检的结论要带出来：渲成功了也可能有标签压着 / 掉出画外，log 里 grep LABEL_ 就知道
        for ln in r.stdout.splitlines():
            if "LABEL_BAD" in ln or "LABEL_STUCK" in ln:
                print("  %s %s" % (shot, ln.strip()), flush=True)
        if not ok:
            print(r.stdout[-1200:], flush=True)
            fails.append(shot)
            if len(fails) > 3:                     # 单镜失败不拖垮整夜，但连挂 4 个就是系统性问题
                raise SystemExit("连续渲染失败太多：" + " ".join(fails))
    if fails:
        print("!! 这些镜头没渲出来，需要单独处理：" + " ".join(fails), flush=True)


def cover():
    """封面：bl_cover.py 渲底图 → cover.py 加 HUD 和标题 → 成品/<片名>_封面.png。

    ⛔ 这一步以前不在链里，final_pass 直接拿封面去做 1.5 秒片头，缺了只会报一句
       ffmpeg 的 `No such file or directory`，看不出是缺封面。0914 补进 post()。
    ⛔ 封面已经存在且比 bl_cover.py 新就跳过——很多片子的封面是手改过的，别覆盖掉。
    """
    png = C.COVER_PNG
    src = os.path.join(HERE, "bl_cover.py")
    if os.path.exists(png) and os.path.getmtime(png) > os.path.getmtime(src):
        print("封面已是最新，跳过：%s" % png, flush=True); return
    step("封面底图（Blender）→ HUD 和标题")
    bg = os.path.join(FILM, "cover_bg.png")
    run([BLENDER, "-b", "--python", src, "--", bg])
    assert os.path.exists(bg), "bl_cover.py 没渲出底图：" + bg
    run([PY, "-X", "utf8", os.path.join(HERE, "cover.py"), bg, png])
    assert os.path.exists(png), "cover.py 没出封面：" + png


def post():
    step("帧序列 → mp4")
    mk("encode")
    step("切段")
    mk("segs")
    step("实测录屏")
    mk("real")
    step("卡片")
    mk("cards")
    step("合成 sub")
    mk("build", "sub")
    step("把逐场景字幕图置空")
    # ⛔ 字幕走 final_pass 的 ASS 一次烧（逐字对齐 + 章节卡 + HUD + 进度条）。
    #    这里不置空的话，build_video 会先把整段字幕烧进 clip，成片就是两层字幕。
    run([PY, "-X", "utf8", os.path.join(HERE, "subs.py"), "blank"])
    step("合成 clip → concat")
    mk("build", "clip")
    mk("build", "concat")
    cover()
    step("字幕 + 封面 + 电平 + BGM 一次编码")
    run([PY, "-X", "utf8", os.path.join(HERE, "final_pass.py"), "final"])
    print("\nCHAIN_OK total %.0fs" % (time.time() - T0), flush=True)


if __name__ == "__main__":
    c = sys.argv[1] if len(sys.argv) > 1 else "all"
    if c == "tts":
        tts(sys.argv[2].split(",") if len(sys.argv) > 2 else None); raise SystemExit(0)
    if c == "cover":
        cover(); raise SystemExit(0)
    if c in ("audio", "all"):
        audio()
    if c in ("render", "all"):
        render(set(sys.argv[2].split(",")) if len(sys.argv) > 2 else None)
    if c in ("post", "all"):
        post()
