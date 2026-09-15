# -*- coding: utf-8 -*-
"""逐字对齐：whisper 词级时间戳 → 每段口播每个「显示字」的 (起, 止) 秒 → work/film/align.json。
make.py storyboard 据此给每个 shot 写切点 "t"，subs.py burn 据此给每条字幕定时（不再按字数比例估）。

    python align.py [cuda|cpu] [p01,p02,...]        ← 要用装了 faster-whisper 的那个解释器

读的是 tts/<id>.wav（后期链之后的最终音轨，rubberband 保时长）。显示字 = 去掉 {{显示|读音}} 里读音侧和 * 之后的字符串，
和 subs.py 的 plain 同一口径。对齐用读音侧文本 vs whisper 文本做 difflib，未匹配段按线性插值。
"""
import os, sys, re, json, difflib
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import config as C  # noqa: E402

FILM = os.path.join(HERE, "work", "film")
MODEL = C.WHISPER_MODEL
PUNCT = "，。！？；：、,.!?;:\"'「」（）()·—-… "


def split_ovr(nar):
    """返回 disp（显示串）、read（读音串）、dmap：disp 每个字 → (read 起, read 止)。均已去掉 *。"""
    disp = ""; read = ""; dmap = []
    i = 0; n = len(nar)
    while i < n:
        m = re.match(r"\{\{([^|{}]*)\|([^|{}]*)\}\}", nar[i:])
        if m:
            a, b = m.group(1), m.group(2); r0 = len(read); read += b
            for ch in a:
                disp += ch; dmap.append((r0, len(read)))
            i += m.end(); continue
        ch = nar[i]; i += 1
        if ch == "*":
            continue
        disp += ch; dmap.append((len(read), len(read) + 1)); read += ch
    return disp, read, dmap


def norm(s):
    """去标点/空格，返回 (norm 串, norm 每字 → 原串下标)。"""
    out = ""; idx = []
    for k, ch in enumerate(s):
        if ch in PUNCT or ch.isspace():
            continue
        out += ch; idx.append(k)
    return out, idx


def align_one(wav, nar, model):
    # ⛔⛔ 0912：`condition_on_previous_text` 默认 True，会让 whisper 在长音频上**解码循环**——
    #    p08（126 秒）的转写里「海力士一家占一半,三星33%,美光18%原因是,」连着出现了 6 次，
    #    而同一个文件单独重转一遍是干净的、切成几秒的短片段也是干净的：**音频没问题，
    #    是解码跑飞了**。后果不是听感，是 check_dup 拿这份转写当证据、报了假的「整段复读」，
    #    差一点让我去切一段本来好好的音频。关掉它。
    #    （逐字时间戳这一路没被带坏——实测 15 段全部单调、无停滞、覆盖 99~100%。）
    segs, info = model.transcribe(wav, language="zh", vad_filter=False, beam_size=5,
                                  word_timestamps=True, condition_on_previous_text=False)
    words = [(w.word, w.start, w.end) for s in segs for w in (s.words or [])]
    got = ""; gt = []                                  # 每个 got 字的 (起, 止)
    for w, s, e in words:
        w = w.strip()
        if not w:
            continue
        n = len(w)
        for k in range(n):
            gt.append((s + (e - s) * k / n, s + (e - s) * (k + 1) / n))
        got += w
    disp, read, dmap = split_ovr(nar)
    nR, iR = norm(read); nG, iG = norm(got)
    sm = difflib.SequenceMatcher(None, nR, nG, autojunk=False)
    rt = [None] * len(read)                            # read 每字 → (起, 止)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                rt[iR[i1 + k]] = gt[iG[j1 + k]]
        else:
            # 未匹配：把 read[i1:i2] 均匀铺在 got[j1:j2] 的时间跨度上（跨度为空则夹在前后之间）
            if j2 > j1:
                t0, t1 = gt[iG[j1]][0], gt[iG[j2 - 1]][1]
            else:
                t0 = gt[iG[j1 - 1]][1] if j1 > 0 else 0.0
                t1 = gt[iG[j1]][0] if j1 < len(iG) else info.duration
            cnt = max(1, i2 - i1)
            for k in range(i2 - i1):
                rt[iR[i1 + k]] = (t0 + (t1 - t0) * k / cnt, t0 + (t1 - t0) * (k + 1) / cnt)
    # 标点等未赋值的读音字：接前一个字的止
    last = 0.0
    for k in range(len(rt)):
        if rt[k] is None:
            rt[k] = (last, last)
        last = rt[k][1]
    T = []
    for (r0, r1) in dmap:
        if r1 > r0:
            T.append([round(rt[r0][0], 3), round(rt[r1 - 1][1], 3)])
        else:
            T.append([round(last, 3), round(last, 3)])
    unmatched = sum(1 for tag, *_ in sm.get_opcodes() if tag != "equal")
    return {"disp": disp, "read": read, "t": T, "dur": round(info.duration, 3), "blocks_unmatched": unmatched, "whisper": got}


def main():
    device = sys.argv[1] if len(sys.argv) > 1 else C.WHISPER_DEVICE
    only = set(sys.argv[2].split(",")) if len(sys.argv) > 2 else None
    sb = json.load(open(os.path.join(FILM, "storyboard.json"), encoding="utf-8"))
    path = os.path.join(FILM, "align.json")
    out = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {}
    from faster_whisper import WhisperModel
    model = WhisperModel(MODEL, device=device, compute_type="float16" if device == "cuda" else "int8")
    for s in sb["scenes"]:
        if only and s["id"] not in only:
            continue
        wav = os.path.join(FILM, "tts", s["id"] + ".wav")
        r = align_one(wav, s["narration"], model)
        out[s["id"]] = r
        print("%s dur %.1fs 显示字 %d 未匹配块 %d 末字止 %.2f" % (s["id"], r["dur"], len(r["disp"]), r["blocks_unmatched"], r["t"][-1][1]), flush=True)
    json.dump(out, open(path, "w", encoding="utf-8"), ensure_ascii=False)
    print("ALIGN_OK", path)


if __name__ == "__main__":
    main()
