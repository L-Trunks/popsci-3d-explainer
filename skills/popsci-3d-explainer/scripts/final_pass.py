# -*- coding: utf-8 -*-
"""成片最后一步，一次编码搞定：封面 xfade + 字幕/章节卡/HUD/进度条 + 配音电平 + BGM。

    python final_pass.py final     正片(work/film/out/<片名>_成片.mp4，无字幕无 BGM) → 成品/<片名>_成片.mp4  约 1 分钟
    python final_pass.py remix     只改音频（BGM 音量/响度）：视频流 -c:v copy，十几秒

以前是 concat → burn → level → splice_cover 三次整片重编码（≈8 分钟）；
现在画面没变就只跑这里。改了画面（clip/concat）才需要前面那条慢链。
"""
import json, os, re, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import config as C  # noqa: E402

FILM = os.path.join(HERE, "work", "film")
OUT = os.path.join(FILM, "out")
BODY = os.path.join(OUT, C.TITLE + "_成片.mp4")
INTRO = os.path.join(OUT, "_cover_intro.mp4")
COVER = C.COVER_PNG
FINAL = C.FINAL_MP4
BGM = os.path.join(FILM, "bgm_mix.mp3")
os.makedirs(C.OUTDIR, exist_ok=True)

COVER_DUR, XF, FADEIN = 1.5, 0.3, 0.35
# 成片响度目标。−14 是 B 站的归一化线，做到 −11.5 平台会压回去一点，但本地播放和下载版直接变响。
# ⛔⛔ 「人声不够大」先量再改：拿同一段渲「只有人声」和「人声+BGM」两条，按 400 ms 一帧比。
#    实测**说话的帧上 BGM 加了 0.00 dB**（三个采样点都是）——侧链闪避早把 BGM 在人声底下
#    压干净了，所以问题是绝对响度，不是被盖。该动的是这个目标值，不是去压 BGM。
#    −12.5 → −11.5 时说话帧 −14.4 → −13.7 dB（限幅吃掉约 0.3 dB），真峰仍 −0.6 dBFS。
TARGET_LUFS = C.TARGET_LUFS
# BGM 音量。⛔ 敢往上抬的依据同上：它只影响**人声间隙**，也就是「气势」本身。
#    侧链闪避 + 两道低频清理到位之后，0.14 → 0.34 一路抬上来，人声间隙的 30–120 Hz
#    反而从 +2.5 降到 +2.1 dB（低频被高通挡住，抬的主要是 300–2k 的弦和铜管）。
BGM_V = C.BGM_V
BGM_HP = C.BGM_HP                             # BGM 的二次高通，见 audio_graph 注释
LIMIT = C.LIMIT                               # 真峰验收线 ≤ −0.3 dBFS，0.88 实测落在 −0.8
VENC = (["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "19", "-b:v", "0"] if os.environ.get("NVENC")
        else ["-c:v", "libx264", "-preset", "medium", "-crf", "18"])


def run(cmd):
    print(">", " ".join(cmd)[:200], flush=True)
    r = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    if r.returncode:
        print(r.stderr[-1500:]); sys.exit(1)


def probe(p, key="duration"):
    return float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=" + key, "-of", "csv=p=0", p], text=True).strip())


def intro():
    """封面 1.5 s 缓推动画，只在封面图更新后重做。"""
    # ⛔ 缺封面时 ffmpeg 只会报 `No such file or directory`，看不出缺的是什么。
    if not os.path.exists(COVER):
        raise SystemExit("没有封面 %s：先跑 `python chain.py cover`（或自己放一张同名图）" % COVER)
    if os.path.exists(INTRO) and os.path.getmtime(INTRO) > os.path.getmtime(COVER):
        return
    W, H = C.CANVAS; fps = C.FPS; N = int(COVER_DUR * fps)
    vf = ("[0:v]scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d,"
          "zoompan=z='1.0+0.04*(pow(min(on/%d,1),2)*(3-2*min(on/%d,1)))':d=%d:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=%dx%d:fps=%d,"
          "fade=t=in:st=0:d=%.2f,format=yuv420p[v]") % (W * 2, H * 2, W * 2, H * 2, N, N, N, W, H, fps, FADEIN)
    run(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-framerate", str(fps), "-i", COVER,
         "-filter_complex", vf, "-map", "[v]", "-t", "%.3f" % COVER_DUR, "-r", str(fps),
         "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", INTRO])


TAIL = os.path.join(OUT, "_tail.mp4")
PY = C.PY_AUDIO


def tail():
    """静默片尾：数据出处卡 + 音乐署名卡，各停 scenes.TAIL_DUR 秒，**没有配音**。

    ⛔⛔ 为什么不是「把最后一段的 narration 清空」：SCENES 里的段一定会被 TTS 走一遍，
       narration 空了，durs 会把它记成 missing、align 的闸门直接挂。
       所以片尾整段**退出 SCENES**（写成 scenes.py 末尾的 TAIL_CARDS / TAIL_DUR），
       在这里拼一段无声视频接到正片后面。
       ⛔ BGM 照常往下走——「片尾不要配音」不等于「片尾不要声音」（见 amix 那条注释）。
    """
    import scenes as SC
    import shots as SB
    if not getattr(SC, "TAIL_CARDS", None):
        open(TAIL, "wb").close()
        raise SystemExit("scenes.py 里没有 TAIL_CARDS：要么加上片尾卡，要么把 final() 里的片尾拼接去掉")
    tdir = os.path.join(OUT, "_tailcards"); os.makedirs(tdir, exist_ok=True)
    specs = [dict(c, id=SB.card_id(c)) for c in SC.TAIL_CARDS]
    cj = os.path.join(tdir, "cards.json")
    json.dump(specs, open(cj, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    run([PY, "-X", "utf8", os.path.join(HERE, "cards2.py"), cj, tdir])
    parts = []
    for i, s in enumerate(specs):
        png = os.path.join(tdir, s["id"] + ".png")
        assert os.path.exists(png), "片尾卡没渲出来：" + png
        mp4 = os.path.join(tdir, "t%d.mp4" % i)
        d = SC.TAIL_DUR
        run(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-framerate", str(C.FPS), "-i", png,
             "-vf", "scale=%d:%d,fade=t=in:st=0:d=0.5,fade=t=out:st=%.2f:d=0.6,"
                    "format=yuv420p,setsar=1,fps=%d" % (C.CANVAS[0], C.CANVAS[1], d - 0.6, C.FPS),
             "-t", "%.3f" % d, "-c:v", "libx264", "-preset", "medium", "-crf", "18", mp4])
        parts.append(mp4)
    lst = os.path.join(tdir, "list.txt")
    open(lst, "w", encoding="utf-8").write("".join("file '%s'\n" % p.replace("\\", "/") for p in parts))
    run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", TAIL])
    print("片尾 %.1fs（%d 张卡，无配音）" % (probe(TAIL), len(parts)))


def body_gain():
    """正片配音（无 BGM）量一次响度，按正片 mtime 缓存。"""
    cache = os.path.join(OUT, "_body_lufs.json"); key = "%d_%d" % (os.path.getmtime(BODY), os.path.getsize(BODY))
    d = json.load(open(cache)) if os.path.exists(cache) else {}
    if d.get("key") != key:
        p = subprocess.run(["ffmpeg", "-i", BODY, "-af", "ebur128=framelog=quiet", "-f", "null", "-"], capture_output=True, text=True, errors="replace")
        d = {"key": key, "I": float(re.search(r"I:\s+(-?[\d.]+) LUFS", p.stderr).group(1))}
        json.dump(d, open(cache, "w"))
    g = TARGET_LUFS - d["I"]
    print("body I=%.1f LUFS → gain %+.1f dB" % (d["I"], g))
    return g


def audio_graph(g, total, body_idx, bgm_idx):
    """人声 + BGM，BGM 走**侧链闪避**。

    ⛔ 「人声间隙里有呜呜声」这句反馈**有两个完全不同的来源**，得分开查：
       ① BGM 的次低频：成片人声间隙里 30–120 Hz 比语音带高 6.6 dB，16.2% 的时刻压过语音；
       ② 人声自己带的段落性隆隆：分段量 30–90 Hz 相对语音带，中位 −18.3 dB，最重的一段只有 −11.9。
    两道一起上：曲子本身在 bgm.py 里已经 90 Hz 高通 + 150 Hz −7 dB；这里再让人声把 BGM 摁下去。
    ⛔ 闪避深度要量：ratio=7 + level_sc=3 实测压了 **22.3 dB**，那不是闪避，是「人声一来
       BGM 消失、一停又蹦回来」，抽吸感很重。threshold=0.030 / ratio=2.6 / level_sc=1 约 **9 dB**，
       刚好。压干净之后 BGM 反而能整体提高——「宏大」听得见，糊却没有了。
    """
    off = COVER_DUR - XF
    # ⛔ 人声支路上串两级 85 Hz 二阶高通（ffmpeg 的 highpass poles 上限就是 2，要陡只能串）。
    #    实测把最脏那一段的 30–90 Hz 从 −11.9 拉到 −19.4 dB，和其他段齐平，120–300 Hz 一点没动。
    # ⛔⛔ **改音色的活，能放进最后一次混音的就别放进素材层。** 回去改 make.py 的 voice()
    #    会连锁：每轮从 tts_raw 重建 → 重插停顿 → 重对齐 → 重出 beats → 所有镜头的帧数全变，
    #    几小时渲染作废。为一段低频不值。
    #
    # ⛔⛔⛔ 「嗡嗡」和「呜呜」是两种东西，别混为一谈——这条查了三轮才查对：
    #    宽带低频隆隆（呜呜）之外，还可能有一条 **窄带稳态哨音（嗡嗡）**：实测 ~299 Hz、
    #    凸出邻域 +12 dB、出现在 75% 的人声间隙，而且**跟段落长度正相关**（长段 +12~+17，
    #    短段只有 +2~+5）——是 TTS 在长段落上自己生出来的，克隆参考音本身是干净的（+1.6）。
    #    85 Hz 高通和 130 Hz 的 EQ **全都在它下面**，一点碰不到它。
    #    定深度要拿「本来就干净的样本」当标尺：有声帧 250–350 Hz 相对 1–3 kHz，
    #    参考音 +5.67、干净段 +2.60；最脏的段 +7.95 → 陷波后 +1.21 落回标尺附近，
    #    再狠到 −24 就掉到 −3.44 = 开始挖人声了。
    # ⛔ 工具选型走了三轮：
    #    ① peaking EQ（equalizer）打不死它——标称 −18 dB，实测凸出只从 +18 降到 +8。
    #       因为它**不是单一频点**：陷掉 299 之后残留峰跑到 302~305，摊在一小片上。
    #    ② afftdn（自适应降噪）完全无效：+18.3 → +19.2。它把纯音当信号，那是对付宽带底噪的。
    #    ③ 定版 = 真陷波（bandreject），**两个中心各来两刀**：+18.3 → +2.8，语音带只损失 0.6 dB。
    #       比「单中心加宽三刀」对 250–350 更温柔（−0.68 vs −1.07），压制力一样。
    #    ⛔ 上了陷波就别再叠宽带衰减：陷波已经从 250–350 取走约 3 dB，再叠一道就真把声音挖薄了。
    # config.audio.notch = [299, 306] 之类；每个中心来两刀。**量出来才填**，别照抄别人的频点。
    _NOTCH = "".join("bandreject=f=%s:width_type=h:width=14," % f for f in (list(C.NOTCH) * 2))
    # ⛔ 这里必须先把整串拼完再 `%`：`%` 的优先级高于 `+`，
    #    写成 "…" + _NOTCH + "…" % (...) 会把格式化只作用在拼接的后半截上，直接 TypeError。
    _GRAPH = ("[%d:a]highpass=f=85:poles=2,highpass=f=85:poles=2,"
              "equalizer=f=130:width_type=o:width=1.4:g=-1," + _NOTCH +
            "equalizer=f=1500:width_type=o:width=1.8:g=2.5,"
            "equalizer=f=3200:width_type=o:width=1.3:g=2.5,"
            # ⛔⛔ 侧链这一路必须补静音（apad）。sidechaincompress 走 framesync，
            #    **两路里短的那路一结束它就收工**——侧链就是人声，人声一完它就停，
            #    于是 BGM 在进 amix 之前已经被截断，只改 amix 的 duration 根本没用
            #    （实测：改成 longest 后音轨长度一秒没变）。
            "volume=%.2fdB,alimiter=limit=0.89:level=disabled,adelay=%d|%d,asplit=2[a0][sc0];"
            "[sc0]apad[sc];"
            # BGM 再收一道低频：曲子进片前已经 90 Hz 高通过一次，成片上量人声间隙里的
            # 30–120 Hz 仍比语音带高 2.8 dB。史诗管弦的「宏大」靠的是 200–2k 的弦和铜管，
            # 100 Hz 以下那截长音鼓垫只贡献「呜呜」。
            # ⛔ 「有部分片段 BGM 声音很小」——量出来是曲子自己的弱段被原样带进来了：
            #    19 分钟的混音里短时电平极差 **25.8 dB**，有一段掉到比中位低 22 dB＝等于没声。
            #    选曲和拼接都不背这个锅，是史诗管弦本身的动态。
            #    用 dynaudnorm 做慢速动态归一（500 ms 帧 + 31 帧高斯窗，等于有人慢慢推推子）：
            #    极差 25.8 → **14.3 dB**，最轻的那段抬了 12 dB，峰值 0.73 不炸。
            #    ⛔ 别用 acompressor：实测 threshold=-24/ratio=3 那档峰值直接顶到 1.000。
            #    中位会被抬 2 dB 上下，所以 dynaudnorm 上了之后 BGM_V 要相应回收一档。
            "[%d:a]highpass=f=%s:poles=2,dynaudnorm=f=500:g=31:p=0.75:m=6:r=0.0:s=12,"
            "volume=%.3f,afade=t=in:st=0:d=0.6,atrim=0:%.3f,afade=t=out:st=%.3f:d=2.5[abr];"
            "[abr][sc]sidechaincompress=threshold=0.030:ratio=2.6:attack=18:release=420:level_sc=1:makeup=1[ab];"
            # ⛔⛔ **峰值和响度是两个独立验收项。** 限幅收到 0.98 时实测成片真峰 +0.7 dBFS
            #    ——采样峰被挡住了，但 AAC 编码后的**峰间**真峰照样冲过 0，已经削顶。
            #    往下收的实测台阶（每提一档响度就要重量一次）：
            #      0.93 → 真峰 −0.4（只富余 0.1，全片素材更多会顶过去）
            #      0.90 → −0.2（响度提到 −12.6 LUFS 之后峰更密，仍不够）
            #      0.88 → −0.8  ← 定版。限幅只削峰不改响度，LUFS 基本不动。
            #    验收线：真峰 TP ≤ −0.3 dBFS。
            # ⛔⛔ duration 必须是 longest，不是 first。first = **第一路输入**（人声），
            #    人声在正片结束那一刻就没了，整条混音会跟着断在那里——**片尾那十几秒的
            #    出处卡是死寂的**。「片尾不要配音」不等于「片尾不要声音」。
            #    BGM 那一路已被 atrim 裁到 total，取最长正好铺满片尾；normalize=0，
            #    人声结束时不会跳电平。
            #    ⛔ 这个坑**看代码推不出来**：按 `-t total` 推理会得出「片尾有 BGM」，
            #    实测 ffprobe 才发现音频流短了一截。音轨长度一律 ffprobe 量，别读代码。
            "[a0][ab]amix=inputs=2:duration=longest:dropout_transition=0:normalize=0,alimiter=limit=%.2f:level=disabled[a]")
    return _GRAPH % (body_idx, g, int(off * 1000), int(off * 1000), bgm_idx, BGM_HP, BGM_V, total, total - 2, LIMIT)


def _need_bgm():
    # ⛔ 没有 bgm_mix.mp3 时 ffmpeg 只报一句「Error opening input」，看不出该跑哪一步
    if not os.path.exists(BGM):
        raise SystemExit("FINAL_FAIL 缺 %s\n先在 config.json 的 bgm.files 填几首曲子，再跑：\n"
                         "  python bgm.py scan\n  python bgm.py mix <成片秒数>" % BGM)


def final():
    _need_bgm()
    import subs
    subs.ass(); sf = subs.subs_filter()
    intro(); tail(); g = body_gain()
    md = probe(BODY); td = probe(TAIL)
    total = COVER_DUR + md - XF + td; off = COVER_DUR - XF
    # ⛔ concat 两条流必须同规格：字幕烧完之后补一道 format/setsar/fps，
    #    片尾那条在 tail() 里已经带了同样三件。不补的话 concat 会静默丢帧或报 SAR 不一致。
    fc = ("[1:v]%s,format=yuv420p,setsar=1,fps=%d[vs];"
          "[0:v]format=yuv420p,setsar=1,fps=%d[vc];"
          "[vc][vs]xfade=transition=fade:duration=%.3f:offset=%.3f[vb];"
          "[3:v]format=yuv420p,setsar=1,fps=%d[vt];"
          "[vb][vt]concat=n=2:v=1:a=0[vx];" % (sf, C.FPS, C.FPS, XF, off, C.FPS)) + audio_graph(g, total, 1, 2)
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", INTRO, "-i", BODY, "-stream_loop", "-1", "-i", BGM,
         "-i", TAIL,
         "-filter_complex", fc, "-map", "[vx]", "-map", "[a]", "-t", "%.3f" % total] + VENC +
        # ⛔ 不用 192k：它在爆破音 + 鼓点上把真峰冲到 +1.6 dBFS（混音 wav 只有 −0.5），256k 回到 −0.6
        ["-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "44100", "-ac", "2", "-b:a", "256k", FINAL])
    print("→ %s  %.1fs（正片 %.1f + 片尾 %.1f）  (BGM_V %.3f, 目标 %.1f LUFS)"
          % (FINAL, probe(FINAL), md, td, BGM_V, TARGET_LUFS))


def remix():
    """视频不动，只重混音：成品视频流 copy + 正片配音 + BGM。"""
    _need_bgm()
    g = body_gain(); total = probe(FINAL)
    tmp = FINAL + ".remix.mp4"
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", FINAL, "-i", BODY, "-stream_loop", "-1", "-i", BGM,
         "-filter_complex", audio_graph(g, total, 1, 2), "-map", "0:v", "-map", "[a]", "-t", "%.3f" % total,
         "-c:v", "copy", "-c:a", "aac", "-ar", "44100", "-ac", "2", "-b:a", "256k", tmp])
    os.replace(tmp, FINAL)
    print("→ %s  %.1fs  (BGM_V %.3f, remix)" % (FINAL, probe(FINAL), BGM_V))


if __name__ == "__main__":
    {"final": final, "remix": remix}[sys.argv[1]]()
