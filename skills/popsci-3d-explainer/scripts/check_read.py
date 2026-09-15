# -*- coding: utf-8 -*-
"""回读检查：把 whisper 听到的**读音**和我们让 TTS 读的**读音**逐音节比，专抓多音字读错。

    python check_read.py            全片
    python check_read.py p06        只看某几段

0910 就是靠这个抓到 VoxCPM 把「一成三」读成「一层三」。
⛔ 按字比会被噪声淹掉（whisper 爱把「三十六」写成 36、把「唾京」写成「拓晶」），
   所以这里比的是拼音序列：字不同但读音一样的，一律不报。
"""
import difflib, json, os, re, sys

from pypinyin import lazy_pinyin, Style

HERE = os.path.dirname(os.path.abspath(__file__))
FILM = os.path.join(HERE, "work", "film")
sys.path.insert(0, HERE)

OVR = re.compile(r"\{\{[^|{}]*\|([^|{}]*)\}\}")
DIG = {"0": "零", "1": "一", "2": "二", "3": "三", "4": "四", "5": "五",
       "6": "六", "7": "七", "8": "八", "9": "九"}


def syl(s):
    """文本 → (音节列表, 每个音节对应的原字)。

    ⛔ 只留汉字：whisper 爱把「三十六」写成 36、把「四零七零踢」写成 4070 Ti，
       数字和字母的写法差异是纯噪声，留着会把真问题淹掉。
    ⛔ 整串一起转拼音（不是逐字），这样「行话」才会出 hang2 而不是 xing2。
    """
    s = "".join(c for c in s if "一" <= c <= "龥")
    py = lazy_pinyin(s, style=Style.TONE3, errors=lambda x: ["?"] * len(x))
    if len(py) != len(s):                      # 极少数情况下对不齐，退回逐字
        py = [(lazy_pinyin(c, style=Style.TONE3) or ["?"])[0] for c in s]
    return [p.lower() for p in py], list(s)


# 「不是读错，是 whisper 听岔」的白名单：(稿里的字, 听成的字)。**逐条核过才往里加**。
# ⛔ 不做模糊匹配（把 zh/z、ch/c、in/ing 一律当同音）——真抓到过的一次读错
#    正是 cheng2/ceng2 这一对（「一成三」读成「一层三」），糊掉就再也抓不到了。
#    宁可逐条白名单，新出现的照样报。片子换了就把下面清空重攒。
SEEN = {
    ("地", "的"), ("条", "调"), ("数", "速"), ("呢", "了"), ("法", "坊"), ("航", "行"),
}


def main():
    al = json.load(open(os.path.join(FILM, "align.json"), encoding="utf-8"))
    from scenes import SCENES
    want = sys.argv[1].split(",") if len(sys.argv) > 1 else None
    hard = 0; tone = 0
    for sc in SCENES:
        sid = sc["id"]
        if want and sid not in want:
            continue
        a = al.get(sid)
        if not a:
            print("!! %s 没有对齐产物" % sid); hard += 1; continue
        rp, rc = syl(OVR.sub(r"\1", sc["narration"]).replace("*", ""))
        gp, gc = syl(a.get("whisper", ""))
        for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, rp, gp, autojunk=False).get_opcodes():
            if tag != "replace" or (i2 - i1) > 3 or (j2 - j1) > 3:
                continue
            x = "".join(rc[i1:i2]); y = "".join(gc[j1:j2])
            px = " ".join(rp[i1:i2]); py = " ".join(gp[j1:j2])
            if re.sub(r"\d", "", px) == re.sub(r"\d", "", py):      # 只差声调
                tone += 1
                print("~  %s 声调 %s(%s) → %s(%s)   …%s…" % (sid, x, px, y, py, "".join(rc[max(0, i1 - 8):i2 + 8])))
            elif (x, y) in SEEN:
                tone += 1
                print("·  %s 已核（听岔）%s → %s" % (sid, x, y))
            else:
                hard += 1
                print("!! %s 读音不同 %s(%s) → %s(%s)   …%s…" % (sid, x, px, y, py, "".join(rc[max(0, i1 - 8):i2 + 8])))
    hard += check_en(al, SCENES, want)
    print("\n读音对不上 %d 处（另有 %d 处只差声调）" % (hard, tone))
    print("READ_" + ("OK" if hard == 0 else "SUSPECT %d" % hard))


EN = re.compile(r"[A-Za-z][A-Za-z0-9]{1,7}")


def check_en(al, SCENES, want):
    """英文缩写有没有被念成别的东西。

    ⛔ 0911 晚间用户「一些英文说的也不标准，比如 4070ti 说成 4070t，cowos 说成哑巴式英语」。
       三轮实测（36 条）结论是 VoxCPM 本来就会念英文，汉字转写才是哑巴英语的来源；
       但它偶尔会在某些上下文里把 DDR5 念成「滴滴阿瓦」、1T 念成「ET」。
    这一关就是抓这类：把要读的英文词和 whisper 听到的英文词按**去掉大小写和空格**比，
    读的那一侧出现过、听的那一侧没有的，就报出来。
    """
    bad = 0
    for sc in SCENES:
        sid = sc["id"]
        if want and sid not in want:
            continue
        a = al.get(sid)
        if not a:
            continue
        read = OVR.sub(r"\1", sc["narration"]).replace("*", "")
        heard = a.get("whisper", "")
        wantset = {w.upper() for w in EN.findall(read)}
        gotset = {w.upper() for w in EN.findall(heard)}
        # 「DDR 5」这类带空格的写法，whisper 会写成 DDR5，所以把空格也抹掉再比一次
        flat_got = re.sub(r"[^A-Z0-9]", "", heard.upper())
        for w in sorted(wantset):
            if w in gotset or w in flat_got:
                continue
            i = read.upper().find(w)
            bad += 1
            print("!! %s 英文没念对 %-8s   …%s…" % (sid, w, read[max(0, i - 12):i + 12]))
    return bad


main()
