# -*- coding: utf-8 -*-
"""转折 / 换内容处插入真停顿。

    python pauses.py            按下表在 tts/*.wav 里补停顿（幂等）
    python pauses.py plan       只打印落点和时间，不改音频
    python pauses.py check      检查每处切口是不是落在静音里（吞音闸门）

为什么不靠标点：实测 TTS **不按标点改停顿长度**——转折处 0.00~0.23 秒，和同段普通停顿
（中位 0.16 秒）没区别。`{{，|。}}` 这类改读音的写法量不出任何效果，只能在波形上开口子。

⛔⛔ 「句子末尾或者开头有上个字的吞音」——病因就在这儿。
第一版按 align 的字边界中点直接下刀，而 whisper 的字边界有 ±100 ms 误差，
实测 **33/33 处全部切在有声处**（切口两侧 −13~−25 dB），等于把每个转折点前
那个字的尾巴齐根削掉。现在改成三条：
  ① 刀口只落在**能量谷底**——在目标时间 ±150 ms 里找最安静的 10 ms 窗口；
  ② 按「目标间隙」补足，不是硬插——本来就有 0.18 s 的缝就只补 0.3 s，
     不然转折处会变成一秒多的大坑；
  ③ 切口两侧各做 12 ms 余弦淡入淡出，杜绝爆音。
⛔ 插完必须重跑 align（字幕和拍点都从 align 出），否则整段错位。
"""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
FILM = os.path.join(HERE, "work", "film")

TURN, SWITCH = 0.52, 0.38      # 转折 / 换内容 的**目标间隙**（含原有的缝）
SEEK = 0.15                    # 找谷底的搜索半径
FADE = 0.012                   # 切口两侧淡入淡出

# (段, 落点串, 目标间隙) —— 落点串是该段显示文本里的**唯一**子串，停顿补在它**前面**。
#
# 这张表是片子内容，不是引擎。写法：
#   TURN   转折处（「但」「错了」「真正的原因」）—— 停久一点
#   SWITCH 换内容处（「再往下是」「第二种说法」）—— 停短一点
# 一段 3~8 处，落在**每个语义转折的第一个字前面**。
#
# ⛔⛔ 落点失效是**静默**的：句子被改掉 / 段被拆开之后，plan() 只打印一行
#    「!! pXX 找不到落点」，日志一长根本看不见，于是那一整段一处停顿都没插过。
#    真栽过：把一段拆成三段之后，四个落点还挂在原段名下，新段整段没插。
#    **改完稿一定要跑 `python pauses.py plan`，逐行看有没有「找不到落点」。**
PAUSES = [
    ("p01", "但问题来了", TURN),
    ("p01", "再往下看", SWITCH),
]
try:                                   # 片子自己的表放 pauses_table.py，覆盖上面的示例
    from pauses_table import PAUSES as _T
    PAUSES = [(a, b, {"TURN": TURN, "SWITCH": SWITCH}.get(c, c) if isinstance(c, str) else c)
              for a, b, c in _T]
except ImportError:
    pass


def plan():
    ap = os.path.join(FILM, "align.json")
    if not os.path.exists(ap):
        print("!! 还没有 align.json（先跑 chain.py audio 的第一遍对齐）")
        return {}
    al = json.load(open(ap, encoding="utf-8"))
    out = {}
    for sid, frag, sec in PAUSES:
        a = al.get(sid)
        if not a:
            print("!! %s 没有对齐产物" % sid); continue
        i = a["disp"].find(frag)
        if i < 0:
            print("!! %s 找不到落点 %r" % (sid, frag)); continue
        if a["disp"].find(frag, i + 1) >= 0:
            print("!! %s 落点不唯一 %r" % (sid, frag)); continue
        if i == 0:
            continue                      # 段首本来就有停顿，不补
        out.setdefault(sid, []).append((round(a["t"][i - 1][1], 3), round(a["t"][i][0], 3), sec, frag))
    for v in out.values():
        v.sort()
    return out


def _valley(x, sr, t, seek=SEEK):
    """在 t 附近找最安静的 10 ms 窗口中心。返回 (样本下标, 该处 dB)。"""
    import numpy as np
    w = int(sr * 0.010)
    lo = max(0, int((t - seek) * sr)); hi = min(len(x) - w, int((t + seek) * sr))
    if hi <= lo:
        return int(t * sr), 0.0
    seg = x[lo:hi + w]
    # 滑动 RMS（用累积和，seek 只有 0.3 秒，直接算也不慢）
    c = np.cumsum(np.concatenate([[0.0], seg ** 2]))
    r = (c[w:] - c[:-w]) / w
    j = int(np.argmin(r))
    return lo + j + w // 2, 10 * float(np.log10(r[j] + 1e-20))


def _gap(x, sr, k, thr_db=-42.0):
    """刀口 k 两侧已有的静音长度（秒）。"""
    import numpy as np
    w = int(sr * 0.008); thr = 10 ** (thr_db / 20)
    def run(step):
        n = 0; i = k
        while 0 <= i - w and i + w <= len(x) and n < int(sr * 0.6):
            seg = x[i:i + w] if step > 0 else x[i - w:i]
            if np.sqrt(np.mean(seg ** 2)) > thr:
                break
            n += w; i += step * w
        return n
    return (run(1) + run(-1)) / sr


REPORT = os.path.join(FILM, "_pauses.json")


def _local_db(x, k, sr, half=0.25):
    import numpy as np
    a = max(0, k - int(sr * half)); b = min(len(x), k + int(sr * half))
    seg = x[a:b]
    seg = seg[np.abs(seg) > 10 ** (-45 / 20)]
    if seg.size < 32:
        return -99.0
    return float(20 * np.log10(np.sqrt(np.mean(seg ** 2)) + 1e-12))


def apply():
    import numpy as np
    import soundfile as sf
    P = plan()
    done = ins = 0
    rep = {}
    for sid, items in sorted(P.items()):
        p = os.path.join(FILM, "tts", sid + ".wav")
        x, sr = sf.read(p, always_2d=True)
        mono = x.mean(1)
        cuts = []
        for t0, t1, sec, frag in items:
            k, db = _valley(mono, sr, (t0 + t1) / 2)
            have = _gap(mono, sr, k)
            need = max(0.0, sec - have)
            cuts.append((k, need, db, have, frag))
        cuts.sort()
        rows = []
        parts = []; last = 0; nf = int(sr * FADE)
        shift = 0.0
        fo = np.cos(np.linspace(0, np.pi / 2, nf))[:, None]
        fi = np.sin(np.linspace(0, np.pi / 2, nf))[:, None]
        prev_cut = False
        for k, need, db, have, frag in cuts:
            if need < 0.05:                       # 本来就够静，不动
                continue
            a = x[last:k].copy()
            # ⛔⛔ 两侧都要淡。第一版只给最末一段做了淡入，于是每处停顿**之后**那一刀都是硬起——
            #    实测 21/65 处切口的「后」侧还在 −17~−30 dB，听上去就是把下一个字的字头削掉了。
            if len(a) > 2 * nf:
                if prev_cut:
                    a[:nf] *= fi
                a[-nf:] *= fo
            parts.append(a)
            # 静音块不用数字零，用**切口附近最安静那 20 ms 的环境底噪**铺满：
            # 纯零会让人听出「断了一下」，铺底噪才像真的停顿。
            q0 = max(0, k - int(sr * 0.05)); q1 = min(len(x), k + int(sr * 0.05))
            room = x[q0:q1]
            n_need = int(need * sr)
            if room.size and float(np.sqrt(np.mean(room ** 2))) < 10 ** (-34 / 20):
                reps = int(n_need / max(len(room), 1)) + 1
                fill = np.tile(room, (reps, 1))[:n_need] * 0.55
            else:
                fill = np.zeros((n_need, x.shape[1]), dtype=x.dtype)
            parts.append(fill.astype(x.dtype))
            rows.append(dict(t=round(k / sr + shift, 3), need=round(need, 3),
                             valley=round(_local_db(mono, k, sr, 0.02), 1),
                             local=round(_local_db(mono, k, sr, 0.25), 1), frag=frag))
            shift += need
            last = k; ins += 1; prev_cut = True
        tail = x[last:].copy()
        if len(tail) > nf and prev_cut:
            tail[:nf] *= fi
        parts.append(tail)
        y = np.concatenate(parts, axis=0)
        sf.write(p, y, sr)
        rep[sid] = rows
        print("%-4s 补了 %d 处，%.1fs → %.1fs" % (sid, sum(1 for c in cuts if c[1] >= 0.05), len(x) / sr, len(y) / sr))
        done += 1
    print("共改 %d 段 · 实插 %d 处（表里 %d 处，其余本来就够静）" % (done, ins, sum(len(v) for v in P.values())))
    json.dump(rep, open(REPORT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("PAUSE_OK  ⛔ 接下来必须重跑 align")


DEPTH = 12.0        # 刀口谷底要比周围语音低这么多 dB，才算「落在字与字之间」


def check():
    """吞音闸门：只查**我们自己插的**那几十刀，不查 TTS 本来就有的停顿。

    ⛔ 判据换过三次，前两次都是错的：
      ① 找「数字零」段——静音块现在铺的是环境底噪，根本找不到；
      ② 量紧挨着的 20 ms ≤ −38 dB——插完两侧有 12 ms 淡入淡出，那儿必然是渐变，苛求；
      ③ 量离切口 60 ms 外的电平——把 TTS 自带的 287 处自然停顿全算进来了，96 处「不合格」
         其实是正常连读，没有区分度。
    现在的判据：刀口那 40 ms 的电平要比它周围 ±250 ms 的语音电平**低 12 dB 以上**。
    低得不够，就说明这一刀砍在一个字的中间，而不是字与字之间。
    """
    if not os.path.exists(REPORT):
        print("!! 没有 _pauses.json，先跑 pauses.apply()"); return 1
    rep = json.load(open(REPORT, encoding="utf-8"))
    bad = tot = 0
    worst = []
    for sid, rows in sorted(rep.items()):
        for r in rows:
            tot += 1
            d = r["local"] - r["valley"]
            worst.append((d, sid, r))
            if d < DEPTH:
                bad += 1
                print("  吞音 %-4s %7.2fs 停%.2fs  谷底 %.1f dB / 周围 %.1f dB（只低 %.1f dB）  %s"
                      % (sid, r["t"], r["need"], r["valley"], r["local"], d, r["frag"]))
    worst.sort(key=lambda x: x[0])     # ⛔ 只按深度排；元组里第三项是 dict，两条深度相同就会比到它上面去
    if worst:
        print("  最浅的三刀：" + " | ".join("%s %s 低 %.1f dB" % (s, r["frag"], d) for d, s, r in worst[:3]))
    print("自插停顿 %d 处，切在字中间 %d 处" % (tot, bad))
    print("PAUSE_CHECK_OK" if bad == 0 else "PAUSE_CHECK_FAIL")
    return bad


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "apply"
    if cmd == "plan":
        for sid, v in sorted(plan().items()):
            for t0, t1, sec, frag in v:
                print("%-4s %7.2fs  目标间隙 %.2fs  %s" % (sid, (t0 + t1) / 2, sec, frag))
    elif cmd == "check":
        sys.exit(1 if check() else 0)
    else:
        apply()
