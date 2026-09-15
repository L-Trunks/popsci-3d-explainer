# -*- coding: utf-8 -*-
"""查 TTS 有没有**整段重复 / 整段吞掉**。

    python check_dup.py            全片每一段
    python check_dup.py p02        只看某几段

⛔⛔ 这是 check_read.py 盖不住的一类事故。那个脚本按拼音序列比，只报 difflib 的
   `replace`（而且限制 ≤3 个音节）——VoxCPM 在长段落上偶尔会**跳回去重念一遍**，
   那是一个几十个音节的 `insert`，它一条都不报。
   0912 实测：p02 从第 19 秒起把开头 19 秒整个重念了一遍，字幕因此有一条挂了 20.26 秒。

判据：把 whisper 回读的拼音序列和稿子的拼音序列对齐，任何 ≥8 个音节的
insert（多出来的＝重复或幻听）或 delete（少掉的＝吞段）都报出来。
"""
import difflib, json, os, re, sys

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
FILM = os.path.join(HERE, "work", "film")
sys.path.insert(0, HERE)

from pypinyin import lazy_pinyin, Style  # noqa: E402

OVR = re.compile(r"\{\{[^|{}]*\|([^|{}]*)\}\}")
MIN = 8          # 多出/少掉这么多个音节才算事故


# ⛔ whisper 把「百分之八十七」写成「87%」、「一千个」写成「1000个」——而下面只留汉字，
#    阿拉伯数字直接没了，于是稿子那边的中文数字整串变成「吞掉了 8 个音节」的假警报。
#    两边都把中文数字字符去掉，比的是数字**以外**的内容；整段重复几十个音节照样露馅。
NUM = set("〇零一二三四五六七八九十百千万亿两")


def syl(s):
    s = "".join(c for c in s if "一" <= c <= "龥" and c not in NUM)
    py = lazy_pinyin(s, style=Style.NORMAL, errors=lambda x: ["?"] * len(x))
    if len(py) != len(s):
        py = [(lazy_pinyin(c) or ["?"])[0] for c in s]
    return [p.lower() for p in py], list(s)


_M = [None]
WIN = 25.0        # 二审的窗口秒数：够长能听懂上下文，够短不会触发解码循环


def _rescan(sid, dur):
    """二审：把这一段切成 25 秒的小窗逐窗转写再拼起来，返回一份干净的转写。

    ⛔⛔ 0912 血的教训：一审的证据（align.json 里那份 whisper 全文）**自己会跑飞**。
       某一段那份里同一句话连着循环 6 次，一审报「多出 47 音节」；
       可同一个文件重转一遍是干净的、切成几秒的短片段也是干净的——**音频没问题，
       是 whisper 在长音频上解码循环**。差一点让我去切一段本来好好的音频。
    ⛔ 所以不能只加 `condition_on_previous_text=False` 就完事：那只是降低复发概率，
       这道二审是兜底——**判「音频有事故」之前，必须拿一份不会循环的转写复核。**
    ⛔ 为什么不按字符位置切「可疑那一句」：稿子的读音侧、显示侧、去数字侧三套索引
       各不相同（`{{重庆|虫庆}}` 两侧字数相同但字不同），映射来映射去很容易错位。
       整段分窗重转最笨，也最不会错。
    """
    import subprocess, tempfile
    if _M[0] is None:
        from faster_whisper import WhisperModel
        _M[0] = WhisperModel("large-v3", device="cuda", compute_type="float16")
    src = os.path.join(FILM, "tts", sid + ".wav")
    out, t = [], 0.0
    while t < dur:
        d = min(WIN, dur - t)
        if d < 0.5:
            break
        w = os.path.join(tempfile.gettempdir(), "duprescan_%s_%d.wav" % (sid, int(t)))
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", "%.2f" % t, "-i", src,
                        "-t", "%.2f" % d, "-ac", "1", "-ar", "16000", w], check=True)
        segs, _ = _M[0].transcribe(w, language="zh", beam_size=5, condition_on_previous_text=False)
        out.append("".join(s.text for s in segs))
        t += WIN - 0.8          # 窗口之间留 0.8 秒重叠，免得切在字上丢音
    return "".join(out)


def _issues(rp, rc, gp, gc):
    """拿两条音节序列比，返回 [(类型, 描述)]。"""
    out = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, rp, gp, autojunk=False).get_opcodes():
        if tag == "insert" and (j2 - j1) >= MIN:
            out.append(("多出 %d 个音节（重复/幻听）" % (j2 - j1), "".join(gc[j1:j2])[:60]))
        elif tag == "delete" and (i2 - i1) >= MIN:
            out.append(("少掉 %d 个音节（吞段）" % (i2 - i1), "".join(rc[i1:i2])[:60]))
        elif tag == "replace" and abs((j2 - j1) - (i2 - i1)) >= MIN:
            out.append(("长度差 %d 个音节" % ((j2 - j1) - (i2 - i1)),
                        "稿「%s」→ 听「%s」" % ("".join(rc[i1:i2])[:40], "".join(gc[j1:j2])[:40])))
    return out


def main():
    al = json.load(open(os.path.join(FILM, "align.json"), encoding="utf-8"))
    from scenes import SCENES
    want = sys.argv[1].split(",") if len(sys.argv) > 1 else None
    bad = 0
    for sc in SCENES:
        sid = sc["id"]
        if want and sid not in want:
            continue
        a = al.get(sid)
        if not a:
            print("!! %s 没有对齐产物" % sid); bad += 1; continue
        rp, rc = syl(OVR.sub(r"\1", sc["narration"]).replace("*", ""))
        gp, gc = syl(a.get("whisper", ""))
        first = _issues(rp, rc, gp, gc)
        if not first:
            continue
        # ── 二审：换一份不会循环的转写再判一次 ──────────────────────────────
        gp2, gc2 = syl(_rescan(sid, a["dur"]))
        second = _issues(rp, rc, gp2, gc2)
        if not second:
            print("~  %s 一审报 %d 处（%s），**二审分窗重转后全部消失**——"
                  "判为 whisper 长音频解码循环，音频没问题，放行"
                  % (sid, len(first), "；".join(t for t, _ in first)))
            continue
        for t, d in second:
            bad += 1
            print("!! %s %s：%s" % (sid, t, d))
        if len(second) < len(first):
            print("   （一审 %d 处、二审剩 %d 处，差额是 whisper 自己的循环）" % (len(first), len(second)))
        # 再看一眼总长：回读比稿子长 8% 以上，多半是有重复
        if len(gp) > len(rp) * 1.08:
            print("~  %s 回读 %d 音节 vs 稿 %d 音节（长了 %.0f%%）" % (sid, len(gp), len(rp), 100 * (len(gp) / len(rp) - 1)))
    print("\n整段重复 / 吞段 %d 处" % bad)
    print("DUP_OK" if bad == 0 else "DUP_FAIL %d" % bad)
    return bad


sys.exit(1 if main() else 0)
