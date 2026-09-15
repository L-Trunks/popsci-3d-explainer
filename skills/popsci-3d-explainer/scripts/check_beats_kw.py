# -*- coding: utf-8 -*-
"""闸门②：镜头脚本里 `B.f("关键词")` 的词必须真的出现在那一块的口播里。

⛔⛔ 找不到词只会**静默退回默认帧**——动画和口播错开，一个错误都不报。
   改稿时顺手动了一个字，就可能打断一个拍点词（真栽过：把「内存」顺手改成「内存条」）。
    python check_beats_kw.py
"""
import io, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import config as C  # noqa: E402
from scenes import SCENES  # noqa: E402

OVR = re.compile(r"\{\{([^|{}]*)\|[^|{}]*\}\}")


def blocks():
    out = {}
    for sc in SCENES:
        disp = OVR.sub(r"\1", sc["narration"]).replace("*", "")
        sh = sc["visual"]["shots"]
        for i, s in enumerate(sh):
            if "seg" not in s:
                continue
            o0 = s["off"]; o1 = sh[i + 1]["off"] if i + 1 < len(sh) else len(disp)
            out[s["seg"]] = disp[o0:o1]
    return out


def main():
    B = blocks()
    bad = 0; n = 0
    for fn in C.SHOT_FILES:
        src = io.open(os.path.join(HERE, fn), encoding="utf-8").read()
        for m in re.finditer(r'_b\("(S\d+[a-z])"', src):
            seg = m.group(1)
            j = src.find('_b("', m.end())
            body = src[m.end():j if j > 0 else len(src)]
            txt = B.get(seg)
            if txt is None:
                print("!! %s 不在分镜里（%s）" % (seg, fn)); bad += 1; continue
            for k in re.finditer(r'B\.(?:f|end)\("([^"]+)"', body):
                n += 1
                if k.group(1) not in txt:
                    print("!! %s 找不到拍点词 %r\n   口播：%s" % (seg, k.group(1), txt[:70])); bad += 1
    print("\n查了 %d 个拍点词，%s" % (n, "全部命中" if not bad else "%d 个对不上" % bad))
    print("KW_" + ("OK" if not bad else "FAIL %d" % bad))


main()
