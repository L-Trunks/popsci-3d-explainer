# -*- coding: utf-8 -*-
"""成片流水线（产物全在 work/film/，成片进 成品/）。

    python make.py encode      Blender 帧序列 → work/blender/Sx.mp4
    python make.py segs        按 shots.SEGS 切段 → work/blender/seg/*.mp4（末帧克隆 +4s）
    python make.py cards       深色卡片 + 打字机名词卡 → work/film/cards/
    python make.py real        实测素材（终端 / 图表）→ work/film/real/
    python make.py storyboard  → work/film/storyboard.json
    python make.py durs        tts/*.wav → _durs.json
    python make.py build       build_video.py --only sub → clip → concat
    python final_pass.py final 画面没变时只跑这个：封面+字幕+电平+BGM 一次编码 ≈1 分钟；remix 只换音频 ≈15 秒
配音走 `python chain.py tts`（后端在 config.json 里选）。
"""
import glob, json, os, sys, subprocess, shutil, hashlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import config as C  # noqa: E402
import shots as SB  # noqa: E402

FILM, BL = SB.FILM, SB.BL
PIPE = HERE                      # build_video.py 就在同目录
PY = C.PY_AUDIO


def run(cmd, **kw):
    print(">", " ".join(str(c) for c in cmd)[:160], flush=True)
    subprocess.run(cmd, check=True, **kw)


def dur_of(p):
    return float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nk=1:nw=1", p], text=True).strip())


def encode():
    for s in sorted(os.listdir(BL)):
        d = os.path.join(BL, s)
        if not os.path.isdir(d) or not os.path.exists(os.path.join(d, "done.txt")):
            continue
        out = os.path.join(BL, s + ".mp4")
        if os.path.exists(out) and os.path.getmtime(out) > os.path.getmtime(os.path.join(d, "done.txt")):
            continue
        run(["ffmpeg", "-y", "-v", "error", "-framerate", str(C.FPS), "-i", os.path.join(d, "f_%04d.png"), "-c:v", "libx264", "-preset", "slow", "-crf", "17", "-pix_fmt", "yuv420p", out])
        print(s, "%.2fs" % dur_of(out))


def segs():
    os.makedirs(os.path.join(BL, "seg"), exist_ok=True)
    for name, ent in SB.SEGS.items():
        shot, a, b = ent[0], ent[1], ent[2]; tpad = ent[3] if len(ent) > 3 else 4.0
        src = os.path.join(BL, shot + ".mp4")
        if not os.path.exists(src):
            print("skip", name, "(no", shot, ")"); continue
        out = os.path.join(BL, "seg", name + ".mp4")
        bj = os.path.join(FILM, "beats.json")
        if os.path.exists(out) and os.path.getmtime(out) > os.path.getmtime(src) and (not os.path.exists(bj) or os.path.getmtime(out) > os.path.getmtime(bj)):
            continue
        run(["ffmpeg", "-y", "-v", "error", "-ss", "%.3f" % a, "-t", "%.3f" % (b - a), "-i", src,
             "-vf", "tpad=stop_mode=clone:stop_duration=%.2f,setpts=PTS-STARTPTS" % tpad, "-c:v", "libx264", "-preset", "medium", "-crf", "17", "-pix_fmt", "yuv420p", "-an", out])
    print("segs", len(os.listdir(os.path.join(BL, "seg"))))


def _walk_visuals():
    for sc in SB.SCENES:
        v = sc["visual"]
        for x in (v["shots"] if "shots" in v else [v]):
            yield sc, x


def cards():
    cdir = os.path.join(FILM, "cards"); os.makedirs(cdir, exist_ok=True)
    specs = {}; tws = {}
    for sc, x in _walk_visuals():
        if "card" in x:
            specs[SB.card_id(x["card"])] = dict(x["card"], id=SB.card_id(x["card"]))
        if "tw" in x:
            tid = "tw_" + hashlib.md5(x["tw"]["text"].encode("utf-8")).hexdigest()[:8]
            tws[tid] = dict(id=tid, text=x["tw"]["text"], sub=x["tw"].get("sub", ""))
    cj = os.path.join(FILM, "cards.json"); json.dump(list(specs.values()), open(cj, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    run([PY, os.path.join(HERE, "cards2.py"), cj, cdir])
    print("cards", len(specs))


def real():
    """实测素材（终端录屏 / 本机跑分）。没有 `{"real": ...}` 的块就直接跳过。

    讲原理的段落都是「它是这样」，这一段是「我在自己这台机器上量的」，
    是片子里唯一的第一手内容。有条件就留一段，可信度完全不是一个量级。
    """
    need = sorted({x["real"] for _, x in _walk_visuals() if "real" in x})
    if not need:
        print("real: 本片没有实测块，跳过"); return
    rdir = os.path.join(FILM, "real"); os.makedirs(rdir, exist_ok=True)
    for n in need:
        gen = os.path.join(HERE, n + ".py")
        assert os.path.exists(gen), "实测块 %r 要有一个同名生成器 %s" % (n, gen)
        run([PY, gen, "render", os.path.join(rdir, n + ".mp4")])
    print("real", os.listdir(rdir))


def _resolve(x):
    f = SB.visual_files(x)[0]
    out = {"src": f}
    if "seek" in x:
        out["seek"] = x["seek"]
    if "at" in x:
        out["at"] = x["at"]
    if "off" in x:
        out["off"] = x["off"]
    if "still" in x:
        out["kb"] = True
    if "card" in x:
        out["kb"] = 0.0003          # 卡片也慢推（beat-driven-explainer：静止 >1.5 s 要加呼吸）
    return out


HEAD_PAD = 0.15
BGM = os.path.join(FILM, "bgm_mix.mp3")      # bgm.py mix 的产物；final_pass 从封面第 1 帧整段垫


def _inject_t(sid, shots, nar, align):
    """align.json（align.py 产物）有这段时，把每个 shot 的切点写成绝对秒 "t"（含 head_pad）。"""
    a = align.get(sid)
    if not a:
        return
    import re as _re
    disp = _re.sub(r"\{\{([^|{}]*)\|[^|{}]*\}\}", r"\1", nar).replace("*", "")
    if disp != a["disp"]:
        print("!! align 过期", sid, "（先重跑 align.py）"); return
    pos = -1
    for k, sh in enumerate(shots):
        if sh.get("off") is not None:
            p = min(int(sh["off"]), len(disp) - 1)
        else:
            p = disp.find(sh["at"], pos + 1) if sh.get("at") else -1
            if p < 0:
                p = pos + 1
        pos = p
        sh["t"] = 0.0 if k == 0 else round(HEAD_PAD + a["t"][p][0], 3)


def storyboard():
    scenes = []
    ap = os.path.join(FILM, "align.json")
    align = json.load(open(ap, encoding="utf-8")) if os.path.exists(ap) else {}
    for sc in SB.SCENES:
        s = {"id": sc["id"], "narration": sc["narration"]}
        if sc.get("rel"):
            s["rel"] = sc["rel"]
        v = sc["visual"]
        if "shots" in v:
            s["shots"] = [_resolve(x) for x in v["shots"]]
            _inject_t(sc["id"], s["shots"], sc["narration"], align)
        else:
            r = _resolve(v); s["visual"] = r["src"]
            if "seek" in r:
                s["seek"] = r["seek"]
            if "card" in v:
                s["motion"] = "drift"
        scenes.append(s)
    cfg = {"title": C.TITLE, "fps": C.FPS, "head_pad": HEAD_PAD, "tail_pad": 0.45, "min_dur": 1.8,
           "transition": 0.3, "shot_xfade": 0.26, "grade": False,
           "outfile": C.TITLE + "_成片",
           "bgm": "", "bgm_vol": 0.0,     # ⛔ BGM 不在 concat 阶段混，统一由 final_pass 一次垫（见 05-混音与BGM）
           "profiles": [{"name": "h", "canvas": list(C.CANVAS), "cards": "cards", "suffix": "", "sub_size": 46}],
           "scenes": scenes}
    os.makedirs(FILM, exist_ok=True)
    json.dump(cfg, open(os.path.join(FILM, "storyboard.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("storyboard", len(scenes), "scenes")


def beats():
    """align.json + storyboard → work/film/beats.json：每个 Blender 镜头块的总帧数 N、显示文本、每字相对块首的 (起,止) 秒。
    镜头脚本用 L.beats("S25") 取 B.N / B.f("关键词") 打关键帧（拍点驱动，见 skill beat-driven-explainer）。"""
    import re as _re, math
    a = json.load(open(os.path.join(FILM, "align.json"), encoding="utf-8"))
    sb = json.load(open(os.path.join(FILM, "storyboard.json"), encoding="utf-8"))
    durs = json.load(open(os.path.join(FILM, "_durs.json")))
    out = {}
    for s in sb["scenes"]:
        al = a.get(s["id"])
        if not al:
            print("!! no align for", s["id"]); continue
        disp = al["disp"]; shots = s["shots"]
        D = HEAD_PAD + durs[s["id"]] + sb.get("tail_pad", 0.45)
        for k, sh in enumerate(shots):
            m = _re.search(r"seg/([A-Za-z0-9]+)\.mp4$", sh["src"])
            if not m:
                continue
            o0 = sh["off"]; o1 = shots[k + 1]["off"] if k + 1 < len(shots) else len(disp)
            t0 = sh["t"]; t1 = shots[k + 1]["t"] if k + 1 < len(shots) else D
            base = HEAD_PAD + al["t"][o0][0] if k else 0.0
            base = t0 if k else 0.0
            rel = [[round(HEAD_PAD + x[0] - base, 3), round(HEAD_PAD + x[1] - base, 3)] for x in al["t"][o0:o1]]
            out[m.group(1)] = {"N": int(math.ceil((t1 - t0 + 0.5) * 30)), "dur": round(t1 - t0, 3), "text": disp[o0:o1], "t": rel, "scene": s["id"]}
    json.dump(out, open(os.path.join(FILM, "beats.json"), "w", encoding="utf-8"), ensure_ascii=False)
    print("beats", len(out), "segs;", " ".join("%s=%d" % (k, v["N"]) for k, v in list(out.items())[:8]), "...")


VOICE_CHAIN = ("rubberband=pitch=0.944:formant=preserved,highpass=f=95,lowshelf=f=150:g=1.5:w=0.7,"
               "equalizer=f=230:t=q:w=1.3:g=1.5,equalizer=f=400:t=q:w=1.4:g=-2.5,equalizer=f=2600:t=q:w=1.2:g=1.5,"
               "deesser=i=0.35:m=0.5:f=0.6,acompressor=threshold=-20dB:ratio=3:attack=15:release=180:makeup=5,"
               "asoftclip=type=tanh:threshold=0.85,alimiter=limit=0.95:level=disabled")


SEG_LUFS = C.SEG_LUFS


def _level_ride(src, dst, window=1.6, max_db=8.0, floor_db=-45.0):
    """段内电平骑行：把慢速的响度漂移抹平，但不碰逐字的微动态。

    ⛔ 0911 晚间用户「我的声音会忽大忽小」。实测段内 3 秒短时电平极差 13.4 dB
       （p10 一段内就差 12.5 dB），只做逐段静态增益完全盖不住。
    这里不用压缩器（0910 用户听后期链觉得「嗡嗡」，压缩器会改音色），
    改用**增益骑行**：算一条 1.6 秒窗口的响度包络，取它的倒数当增益曲线，
    再把曲线本身平滑到「每 100 ms 最多动 0.35 dB」——听感上等于有人在旁边推推子，
    音色一点不动。静音段的增益冻结在前一个有声值上，免得把底噪抬起来。
    """
    import numpy as np
    import soundfile as sf
    x, sr = sf.read(src, always_2d=True)
    m = x.mean(1)
    hop = int(sr * 0.05); w = int(sr * window)
    n = max(1, (len(m) - w) // hop + 1)
    c = np.cumsum(np.concatenate([[0.0], m ** 2]))
    idx = np.arange(n) * hop
    rms = np.sqrt((c[np.minimum(idx + w, len(m))] - c[idx]) / w)
    db = 20 * np.log10(rms + 1e-12)
    act = db > floor_db
    if act.sum() < 4:
        shutil.copy2(src, dst); return 0.0
    tgt = float(np.median(db[act]))
    g = np.where(act, tgt - db, np.nan)
    # 静音处沿用前后最近的有声增益，避免抬底噪
    ii = np.arange(n); good = ~np.isnan(g)
    g = np.interp(ii, ii[good], g[good])
    g = np.clip(g, -max_db, max_db)
    # 限制爬升率：每步（50 ms）最多 0.175 dB
    for _ in range(2):
        for a, b in ((1, n), (n - 2, -1)):
            step = 1 if b > a else -1
            for k in range(a, b, step):
                g[k] = min(max(g[k], g[k - step] - 0.175), g[k - step] + 0.175)
    gs = np.interp(np.arange(len(m)), idx + w // 2, g)
    y = x * (10 ** (gs / 20))[:, None]
    y = np.clip(y, -0.99, 0.99)
    sf.write(dst, y, sr)
    return float(g.max() - g.min())


def voice(ids):
    """tts_raw/<id>.wav → tts/<id>.wav：去次低频 → 段内电平骑行 → 对齐到 SEG_LUFS → 限幅。"""
    raw = os.path.join(FILM, "tts_raw"); out = os.path.join(FILM, "tts")
    import re, tempfile
    for i in ids:
        # 0910 用户：整条后期链听着「嗡嗡」，所以不上压缩器/EQ 染色，只做下面三件不改音色的事
        src = os.path.join(raw, i + ".wav")
        t1 = os.path.join(tempfile.gettempdir(), "_v1_%s.wav" % i)
        t2 = os.path.join(tempfile.gettempdir(), "_v2_%s.wav" % i)
        # ① 70 Hz 以下切掉：人声基频最低也在 85 Hz 以上，这一刀只去隆隆声不动音色
        run(["ffmpeg", "-y", "-v", "error", "-i", src, "-af", "highpass=f=70:poles=2", t1])
        # ② 段内电平骑行
        spread = _level_ride(t1, t2)
        # ③ 各段静态增益对齐（VoxCPM 逐段响度差 2~5 dB）+ 限幅
        p = subprocess.run(["ffmpeg", "-i", t2, "-af", "ebur128=framelog=quiet", "-f", "null", "-"], capture_output=True, text=True, errors="replace")
        g = SEG_LUFS - float(re.search(r"I:\s+(-?[\d.]+) LUFS", p.stderr).group(1))
        run(["ffmpeg", "-y", "-v", "error", "-i", t2, "-af", "volume=%.2fdB,alimiter=limit=0.95:level=disabled" % g, os.path.join(out, i + ".wav")])
        for t in (t1, t2):
            if os.path.exists(t):
                os.remove(t)
        print("voice %s %.2fs 骑行跨度 %.1f dB, 静态 %+.1f dB" % (i, dur_of(os.path.join(out, i + ".wav")), spread, g))


def durs():
    d = {}
    for sc in SB.SCENES:
        p = SB.tts_path(sc)
        d[sc["id"]] = dur_of(p) if os.path.exists(p) else 0.0
    json.dump(d, open(os.path.join(FILM, "_durs.json"), "w"), indent=0)
    miss = [k for k, v in d.items() if v == 0]
    print("durs", len(d), "missing", miss, "total %.1fs" % sum(d.values()))


# 镜头之间的溶解转场做在 build_video.build_shots_clip 里（storyboard 的 shot_xfade=0.26），
# 段与段之间由 transition=0.3 负责。两者都不改总时长，subs.py 也已经按 transition 扣过接缝。


def build(stages=("sub", "clip", "concat")):
    for st in stages:
        run([C.PY_BUILD, os.path.join(PIPE, "build_video.py"), os.path.join(FILM, "storyboard.json"), "--only", st, "--profile", "h"])


def reclip(ids):
    """只重出指定场景的 clip（改了个别画面后用），然后要再跑 build concat。"""
    sys.path.insert(0, PIPE)
    import build_video as BV
    cfg = json.load(open(os.path.join(FILM, "storyboard.json"), encoding="utf-8"))
    scenes = [s for s in cfg["scenes"] if s["id"] in ids]
    durs = json.load(open(os.path.join(FILM, "_durs.json")))
    prof = cfg["profiles"][0]
    BV.stage_sub(cfg, scenes, FILM, prof)
    # 段落级配音 + 条级字幕：clip 里不烧整段字幕（subs.py burn 后烧），这里把刚生成的字幕图置空
    from PIL import Image
    for s in scenes:
        Image.new("RGBA", tuple(C.CANVAS), (0, 0, 0, 0)).save(os.path.join(FILM, "sub_" + prof["name"], s["id"] + ".png"))
    BV.stage_clip(cfg, scenes, FILM, durs, prof)


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "build" and len(sys.argv) > 2:
        build(tuple(sys.argv[2].split(",")))
    elif cmd == "reclip":
        reclip(set(sys.argv[2].split(",")))
    elif cmd == "voice":
        voice(sys.argv[2].split(","))
    else:
        globals()[cmd]()
