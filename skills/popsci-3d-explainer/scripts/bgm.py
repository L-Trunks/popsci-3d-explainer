# -*- coding: utf-8 -*-
"""挑 BGM 并拼成一条：史诗/大气子集里按能量+起音排序，避开上一支片用过的曲子。

    python bgm.py scan          扫描候选，结果落 work/bgm/scan.json
    python bgm.py mix <秒数>    按排名挑够时长，loudnorm 对齐 + 3 s 交叉淡入 → work/film/bgm_mix.mp3
"""
import glob, json, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import config as C  # noqa: E402

LIB = C.BGM_LIB                 # 曲库根目录（可以为空）
SUBS = C.BGM_SUBS               # 要扫的子目录
USED = [u.lower() for u in (C.get("bgm.used") or [])]   # 上一支片用过的，想避重才填
SKIP_USED = bool(C.get("bgm.skip_used", False))
WORK = os.path.join(HERE, "work", "bgm")
OUT = os.path.join(HERE, "work", "film", "bgm_mix.mp3")


def _candidates():
    """曲库里的所有候选文件。没配曲库就用 config.bgm.files 里点名的那几首。

    免费来源：YouTube Audio Library / Pixabay Music / Free Music Archive（CC0）；
    incompetech（Kevin MacLeod）是 CC-BY，**片尾必须署名**。
    """
    if not LIB:
        return [os.path.abspath(p) for p in C.BGM_FILES]
    out = []
    for sub in SUBS:
        d = os.path.join(LIB, sub) if sub else LIB
        for ext in ("*.mp3", "*.flac", "*.wav", "*.m4a"):
            out += glob.glob(os.path.join(d, ext))
    return sorted(out)


def scan():
    import librosa, numpy as np
    os.makedirs(WORK, exist_ok=True)
    rows = []
    for f in _candidates():
        name = os.path.basename(f)
        if SKIP_USED and any(u in name.lower() for u in USED):
            continue
        try:
            dur = librosa.get_duration(path=f)
            if not (135 <= dur <= 330):
                continue
            y, sr = librosa.load(f, sr=22050, offset=max(0, dur / 2 - 15), duration=30.0)
            if y.size < sr * 5:
                continue
            rms = float(np.sqrt(np.mean(y ** 2)))
            onset = librosa.onset.onset_strength(y=y, sr=sr)
            tempo = float(librosa.beat.tempo(onset_envelope=onset, sr=sr)[0])
            flat = float(np.mean(librosa.feature.spectral_flatness(y=y)))
            # ⛔ 「人声间隙里有呜呜的背景音」实测就是 BGM：成片人声间隙里 30–120 Hz 比语音带
            #    高 6.6 dB，而一批史诗曲有 37.4% 的能量压在 80 Hz 以下。
            #    所以这里量 lowr = 150 Hz 以下的能量占比，进打分做惩罚项。
            Sx = np.abs(np.fft.rfft(y[:min(len(y), sr * 20)] * np.hanning(min(len(y), sr * 20)))) ** 2
            fq = np.fft.rfftfreq(min(len(y), sr * 20), 1 / sr)
            lowr = float(Sx[fq < 150].sum() / max(Sx.sum(), 1e-12))
            mid = float(Sx[(fq >= 500) & (fq < 5000)].sum() / max(Sx.sum(), 1e-12))
            rows.append(dict(f=f, name=name, dur=round(dur, 1), rms=round(rms, 4),
                             onset=round(float(np.mean(onset)), 2), bpm=round(tempo, 1), flat=round(flat, 5),
                             lowr=round(lowr, 4), mid=round(mid, 4)))
        except Exception as e:
            print("skip", name, e)
    # 打分：能量 + 起音强度 + 中频撑得住，惩罚「白噪」和「整首泡在次低频里」的
    for r in rows:
        r["score"] = round(r["rms"] * 2.4 + r["onset"] / 14.0 - r["flat"] * 22
                           - max(0.0, r["lowr"] - 0.30) * 3.2 + r["mid"] * 1.6, 4)
    rows = [r for r in rows if r["lowr"] < 0.62]      # 整首都是闷响的直接不要
    rows.sort(key=lambda r: -r["score"])
    json.dump(rows, open(os.path.join(WORK, "scan.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    for r in rows[:25]:
        print("%-58s %6.1fs rms %.3f onset %5.2f bpm %5.1f  score %.3f" % (r["name"][:56], r["dur"], r["rms"], r["onset"], r["bpm"], r["score"]))
    print("候选", len(rows))


# 定版曲单（config.json 的 bgm.pick，按出场顺序写文件名）。空着就按 scan 的打分自动取前 N 首。
#
# ⛔⛔ 挑曲的两条铁律，都是量出来才发现的：
# ① **打分只听中间 30 秒判不出「这首有一分钟几乎没声」。** 一首 lull=0.29 的曲子
#    （29% 的 10 秒格低于自己中位 3.5 dB）在片子里就是用户说的「中间比较平淡」，
#    其中整整一分钟的 200–2k 能量掉到 1.5 dB = 等于没声。先跑 `bgm.py prof` 量整首再定。
# ② **混音总长必须 > 成片总长。** final_pass 用 `-stream_loop -1` 垫 BGM，短了会绕回开头，
#    听上去像「片尾特意放了开场曲」——那是长度差出来的巧合，不是编排。
#
# 排序原则：lull≈0 + iqr 小 + 中频中位（lvl）高；**最响的放中段**，开场和结尾各留一首标志性的。
PICK = list(C.BGM_PICK)


def prof(n_top=80):
    """⛔⛔ scan() 的打分只听**曲子正中间那 30 秒**，判不出「这首有一分钟几乎没声」这种坑
    ——实测有曲子在 9:00~10:00 那一分钟只有 1.5 dB（比全曲中位低 21 dB），
    另有曲子整整三分钟全程低于中位（听感就是「一直不来劲」）。

    这里改成量**整首**：每 10 秒一格，量 200–2000 Hz（史诗管弦的弦/铜管/合唱都在这一带，
    「宏大」是这一带撑出来的，不是低频鼓垫）。三个指标：
      · lull  = 低于本曲中位 3.5 dB 的格子占比 —— 「有没有塌下去的段落」
      · iqr   = 四分位距 —— 「整首平不平稳」
      · midr  = 200–2k 的中位 − 全带中位 —— 「中频撑不撑得住」（各曲先 loudnorm 到同一响度再比）
    """
    import numpy as np
    import soundfile as sf
    rows = json.load(open(os.path.join(WORK, "scan.json"), encoding="utf-8"))
    rows.sort(key=lambda r: -r["score"])
    seen, uniq = set(), []
    for r in rows:
        if r["name"].lower() in seen:
            continue
        seen.add(r["name"].lower()); uniq.append(r)
    cand = uniq[:n_top]
    for n in PICK:                                   # 现役这几首也一起量，好对照
        for r in uniq:
            if r["name"] == n and r not in cand:
                cand.append(r)
    tmp = os.path.join(WORK, "_p.wav")
    out = []
    for i, r in enumerate(cand):
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", r["f"], "-af",
                        "highpass=f=90:poles=2,equalizer=f=150:width_type=o:width=2:g=-7,"
                        "loudnorm=I=-16:TP=-1.5:LRA=11", "-ac", "1", "-ar", "16000", tmp], check=True)
        x, sr = sf.read(tmp)
        W = sr * 10
        if len(x) < W * 12:
            continue
        mids, fulls = [], []
        for k in range(len(x) // W):
            seg = x[k * W:(k + 1) * W] * np.hanning(W)
            S = np.abs(np.fft.rfft(seg)) ** 2
            f = np.fft.rfftfreq(W, 1 / sr)
            mids.append(10 * np.log10(S[(f >= 200) & (f < 2000)].sum() / W + 1e-12))
            fulls.append(10 * np.log10(S.sum() / W + 1e-12))
        m = np.array(mids)
        med = float(np.median(m))
        out.append(dict(name=r["name"], f=r["f"], dur=r["dur"],
                        lull=round(float((m < med - 3.5).mean()), 3),
                        iqr=round(float(np.percentile(m, 75) - np.percentile(m, 25)), 2),
                        midr=round(med - float(np.median(fulls)), 2),
                        lvl=round(med, 2)))
        print("%3d/%d %-50s lull %.2f iqr %4.1f midr %5.2f" % (i + 1, len(cand), r["name"][:48], out[-1]["lull"], out[-1]["iqr"], out[-1]["midr"]))
    out.sort(key=lambda r: (r["lull"], r["iqr"]))
    json.dump(out, open(os.path.join(WORK, "prof.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\n=== 最稳的 20 首（lull 小＝没有塌段，iqr 小＝全程平稳）===")
    for r in out[:20]:
        print("%-52s %6.1fs lull %.2f iqr %4.1f midr %5.2f" % (r["name"][:50], r["dur"], r["lull"], r["iqr"], r["midr"]))
    print("\n=== 现役曲单 ===")
    for n in PICK:
        for r in out:
            if r["name"] == n:
                print("%-52s %6.1fs lull %.2f iqr %4.1f midr %5.2f" % (n[:50], r["dur"], r["lull"], r["iqr"], r["midr"]))


def _dur(p):
    return float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                          "-of", "csv=p=0", p], text=True).strip())


def _trim_quiet(p, i, drop=6.0, keep=3.0):
    """把一首曲子头尾「比自身中位低 drop dB」的部分剪掉（量的还是 200–2k）。

    keep 是交叉淡化要用掉的秒数，尾巴上多留这么多，免得剪到正响的地方就接下一首。
    """
    import numpy as np
    import soundfile as sf
    x, sr = sf.read(p, always_2d=True)
    m = x.mean(1)
    W = sr * 2
    n = len(m) // W
    if n < 8:
        return p
    lv = []
    for k in range(n):
        seg = m[k * W:(k + 1) * W] * np.hanning(W)
        S = np.abs(np.fft.rfft(seg)) ** 2
        f = np.fft.rfftfreq(W, 1 / sr)
        lv.append(10 * np.log10(S[(f >= 200) & (f < 2000)].sum() / W + 1e-12))
    lv = np.array(lv); thr = np.median(lv) - drop
    good = np.where(lv >= thr)[0]
    if not len(good):
        return p
    a = good[0] * 2.0
    b = min(len(m) / sr, (good[-1] + 1) * 2.0 + keep)
    if b - a < 30 or (a < 1 and b > len(m) / sr - 1):
        return p
    out = p.replace(".wav", "_t.wav")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", p, "-af",
                    "atrim=%.2f:%.2f,asetpts=PTS-STARTPTS" % (a, b), out], check=True)
    return out


def mix(total):
    rows = json.load(open(os.path.join(WORK, "scan.json"), encoding="utf-8"))
    if PICK:
        by = {}
        for r in rows:
            by.setdefault(r["name"], r)
        miss = [n for n in PICK if n not in by]
        assert not miss, "候选里没有这几首：%s" % miss
        rows = [by[n] for n in PICK]
    seen, uniq = set(), []                      # 同一首曲子在多个子集里都有，按文件名去重
    for r in rows:
        k = r["name"].lower()
        if k in seen:
            continue
        seen.add(k); uniq.append(r)
    rows = uniq
    XF = 3.0
    pick, acc = [], 0.0
    for r in rows:
        if acc >= total + 40:
            break
        pick.append(r); acc += r["dur"] - XF
    print("选了 %d 首，合计 %.0fs：" % (len(pick), acc))
    norm = []
    os.makedirs(WORK, exist_ok=True)
    for i, r in enumerate(pick):
        p = os.path.join(WORK, "n%02d.wav" % i)
        # ⛔ 次低频必须先切掉再进片。史诗曲的 braam / 长音鼓垫有三成多能量在 80 Hz 以下，
        #    垫在人声底下就是用户听到的那条「呜呜」。90 Hz 二阶高通 + 220 Hz 以下 −7 dB 搁架，
        #    听感上「宏大」全在中频的铜管和人声合唱里，砍掉的只有糊。
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", r["f"],
                        "-af", "highpass=f=90:poles=2,equalizer=f=150:width_type=o:width=2:g=-7,"
                               "loudnorm=I=-16:TP=-1.5:LRA=11",
                        "-ar", "44100", "-ac", "2", p], check=True)
        # ⛔ 史诗曲十有八九是「渐弱收尾」，前面也常有十几秒的铺垫。两首这样的接在一起，
        #    3 秒交叉淡化正好落在两条尾巴中间——0913 实测接缝处 200–2k 能量掉到 7~10 dB
        #    （比中位低 14~17 dB），听上去就是「音乐没了」。所以进交叉之前先把
        #    **头尾比自身中位低 6 dB 的部分剪掉**，只留下真正有劲的那一段。
        p = _trim_quiet(p, i)
        norm.append(p)
        print("  %2d %-52s %6.1fs" % (i + 1, r["name"][:50], _dur(p)))
    cur = norm[0]
    for i in range(1, len(norm)):
        nxt = os.path.join(WORK, "acc%02d.wav" % i)
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", cur, "-i", norm[i],
                        "-filter_complex", "[0][1]acrossfade=d=%.1f:c1=tri:c2=tri" % XF, nxt], check=True)
        cur = nxt
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", cur, "-b:a", "192k", OUT], check=True)
    d = subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", OUT], text=True).strip()
    print("→", OUT, d, "s")
    json.dump([r["name"] for r in pick], open(os.path.join(WORK, "used.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    if sys.argv[1] == "scan":
        scan()
    elif sys.argv[1] == "prof":
        prof(int(sys.argv[2]) if len(sys.argv) > 2 else 80)
    else:
        mix(float(sys.argv[2]))
