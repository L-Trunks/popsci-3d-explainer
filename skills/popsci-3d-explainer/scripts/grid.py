# -*- coding: utf-8 -*-
"""三层格子，每格盖章绑指纹，指纹一变章自动失效。

    python grid.py                        看格子
    python grid.py --过 稿:p01 --因 "看了什么"
    python grid.py --过 画:S11,S12 --因 "亲眼看了这两镜的哪几帧"
    python grid.py --退 画:S05 "电子看不见"

三层的格子单位**不一样**：
  稿  一段一格    指纹 = md5(口播)
  画  **一镜一格** 指纹 = md5(该镜的分镜规格 + 生成器源码 + 渲出来的帧数)
  段  一段一格    指纹 = 稿指纹 + 该段所有镜的画指纹 + 配音 wav 的 md5

⛔⛔ 判据只能是**自己看画面、自己听声音**（`look.py` 渲大图来看），不是看文件在不在。
⛔⛔ 指纹一变章自动失效——所以「生成器源码」那一项**必须把每个镜头文件都登进去**
   （config.json 的 shot_files）。漏一个，改了那里的镜头、只要帧数没变，旧章还生效 = 假章。
⛔ 「全部盖章」才算可以总装交付；没重渲的镜头要沿用旧章，先用 mtime 证明它的帧文件真没动过。
"""
import argparse, hashlib, json, os, re, sys

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import shots as SB  # noqa: E402

账 = os.path.join(HERE, "work", "film", "验收.json")
BL = os.path.join(HERE, "work", "blender")


def md5s(s):
    return hashlib.md5(s.encode("utf-8")).hexdigest()[:12]


def md5f(p):
    if not os.path.exists(p):
        return "missing"
    h = hashlib.md5()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:12]


def 镜表():
    """全部建模镜：{镜号: (所属段, 该块的分镜规格)}。"""
    out = {}
    for sc in SB.SCENES:
        for sh in sc["visual"]["shots"]:
            if "seg" in sh:
                out[sh["seg"][:-1]] = (sc["id"], sh)
    return out


镜 = 镜表()


def 帧数(shot):
    d = os.path.join(BL, shot, "done.txt")
    try:
        return open(d).read().strip()
    except Exception:
        return "0"


def 指纹(key, layer):
    if layer == "画":
        sid, sh = 镜[key]
        sc = {s["id"]: s for s in SB.SCENES}[sid]
        return md5s(json.dumps(sh, ensure_ascii=False, sort_keys=True)
                    + SB.generator_fingerprint(sc) + 帧数(key))
    sc = {s["id"]: s for s in SB.SCENES}[key]
    if layer == "稿":
        return md5s(sc["narration"])
    segs = [sh["seg"][:-1] for sh in sc["visual"]["shots"] if "seg" in sh]
    return md5s(指纹(key, "稿") + "".join(指纹(x, "画") for x in segs) + md5f(SB.tts_path(sc)))


def 单位(layer):
    return sorted(镜, key=lambda s: int(s[1:])) if layer == "画" else [s["id"] for s in SB.SCENES]


def 有产物(key, layer):
    if layer == "画":
        return os.path.exists(os.path.join(BL, key + ".mp4"))
    sc = {s["id"]: s for s in SB.SCENES}[key]
    return SB.product_exists(sc, "稿" if layer == "稿" else "段")


def 读():
    return json.load(open(账, encoding="utf-8")) if os.path.exists(账) else {}


def 写(d):
    os.makedirs(os.path.dirname(账), exist_ok=True)
    json.dump(d, open(账, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--过", action="append", default=[])
    ap.add_argument("--退", nargs=2, default=None, metavar=("层:格", "原因"))
    ap.add_argument("--因", default="")
    a = ap.parse_args()
    d = 读()
    for item in getattr(a, "过"):
        layer, ids = item.split(":", 1)
        for k in ids.split(","):
            k = k.strip()
            d["%s/%s" % (layer, k)] = {"判": "过", "指纹": 指纹(k, layer), "因": getattr(a, "因")}
        写(d); print("盖章 %s" % item)
    if getattr(a, "退"):
        lk, why = getattr(a, "退"); layer, k = lk.split(":", 1)
        d[lk] = {"判": "退", "指纹": 指纹(k, layer), "因": why}
        写(d); print("打回 %s：%s" % (lk, why))

    total = ok = 0
    for layer in ("稿", "画", "段"):
        us = 单位(layer)
        过, 退, 缺 = [], [], []
        for k in us:
            r = d.get("%s/%s" % (layer, k))
            if not 有产物(k, layer):
                缺.append(k + "(无产物)")
            elif not r or r.get("指纹") != 指纹(k, layer):
                缺.append(k)
            elif r["判"] == "过":
                过.append(k)
            else:
                退.append((k, r.get("因", "")))
        total += len(us); ok += len(过)
        print("\n[%s] %d/%d 已盖章" % (layer, len(过), len(us)))
        if 退:
            print("  打回 %d：" % len(退) + "  ".join("%s(%s)" % x for x in 退))
        if 缺:
            print("  还没看 %d：%s" % (len(缺), " ".join(缺[:40]) + (" …" if len(缺) > 40 else "")))
    if ok == total:
        # ⛔ 这里原来把 14/85/14 写死在提示里，改稿加段、加镜之后就对不上了（实际 15/93/15）。
        #    一律用当场数出来的格数。
        print("\n⭐ 三层全部盖章（稿 %d + 画 %d + 段 %d = %d 格）—— 可以总装交付。"
              % (len(单位("稿")), len(单位("画")), len(单位("段")), total))
    return 0


if __name__ == "__main__":
    sys.exit(main())
