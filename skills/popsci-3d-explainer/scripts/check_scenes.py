# -*- coding: utf-8 -*-
"""闸门①：scenes.py 的口播（去掉读音覆盖后）必须和盖过章的稿 markdown **逐字**一致。

改了 scenes.py 忘了跑 gen_gao.py、或者直接手改了稿，都在这里被抓住。
顺带查两件同样是静默失败的：**素材零复用**（同一个 seg 出现两次会让后一块覆盖前一块的
beats，镜头只渲一小段）、**块首 4 字不含标记**（shots.at 取前 4 字当定位关键词）。"""
import io, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import grid_script as G
from scenes import SCENES


def disp(t):
    return re.sub(r"\{\{([^|{}]*)\|[^|{}]*\}\}", r"\1", t).replace("*", "")


def norm(t):
    return re.sub(r"\s+", "", t)


bad = 0
S = G.segs()
ids = [s["id"] for s in SCENES]
if set(ids) != set(S):
    print("!! 段不匹配 稿:", sorted(set(S) - set(ids)), " 分镜:", sorted(set(ids) - set(S))); bad += 1
for sc in SCENES:
    a = norm(disp(sc["narration"]))
    b = norm(S[sc["id"]][0]) if sc["id"] in S else ""
    if a != b:
        bad += 1
        for i in range(min(len(a), len(b))):
            if a[i] != b[i]:
                print("!! %s 第 %d 字起不一致\n   分镜: …%s…\n   稿  : …%s…" % (sc["id"], i, a[max(0, i - 12):i + 24], b[max(0, i - 12):i + 24]))
                break
        else:
            print("!! %s 长度不同 分镜 %d / 稿 %d\n   尾部差: %r" % (sc["id"], len(a), len(b), (a if len(a) > len(b) else b)[min(len(a), len(b)):][:40]))

# 素材零复用
seen = {}
for sc in SCENES:
    for sh in sc["visual"]["shots"]:
        for k in ("seg", "real"):
            if k in sh:
                key = k + ":" + sh[k]
                if key in seen:
                    print("!! 素材复用", key, seen[key], "→", sc["id"]); bad += 1
                seen[key] = sc["id"]
# 块首 4 字不含标记
for sc in SCENES:
    for sh in sc["visual"]["shots"]:
        if "{" in sh["at"] or "*" in sh["at"] or "|" in sh["at"]:
            print("!! 块首含标记", sc["id"], sh["at"]); bad += 1

nseg = sum(1 for sc in SCENES for sh in sc["visual"]["shots"] if "seg" in sh)
ncard = sum(1 for sc in SCENES for sh in sc["visual"]["shots"] if "card" in sh)
nreal = sum(1 for sc in SCENES for sh in sc["visual"]["shots"] if "real" in sh)
nblk = sum(len(sc["visual"]["shots"]) for sc in SCENES)
print("\n%d 段 %d 块：3D %d · 卡片 %d · 实测 %d" % (len(SCENES), nblk, nseg, ncard, nreal))
print("CHECK_" + ("FAIL %d" % bad if bad else "OK"))
