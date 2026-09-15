# -*- coding: utf-8 -*-
"""成片契约：SCENES（稿 + 画）与 Blender 段切点。

visual 规格：
  {"seg": "S11a"}      Blender 段（work/blender/seg/S11a.mp4），时长由 beats.json 决定
  {"card": {...}}      cards.py / cards2.py 出的深色卡片 png
  {"real": "bench"}    实测录屏 mp4（work/film/real/）
"""
import hashlib, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
FILM = os.path.join(HERE, "work", "film")
BL = os.path.join(HERE, "work", "blender")

sys.path.insert(0, HERE)
import config as C  # noqa: E402
from scenes import SCENES  # noqa: E402

# 每个 3D 块一镜：seg 名 SNNa ← Blender 场景 SNN。时长先给占位，beats.json 出来后被覆盖。
SEGS = {}
for _sc in SCENES:
    for _sh in _sc["visual"]["shots"]:
        if "seg" in _sh:
            SEGS[_sh["seg"]] = (_sh["seg"][:-1], 0.0, 8.0, 0.6)

_bj = os.path.join(FILM, "beats.json")
if os.path.exists(_bj):
    import json as _json
    for _k, _v in _json.load(open(_bj, encoding="utf-8")).items():
        if re.match(r"^S\d+[a-z]$", _k):
            SEGS[_k] = (_k[:-1], 0.0, round(_v["N"] / float(C.FPS), 3), 0.6)


def _src_hash(*files):
    h = hashlib.md5()
    for f in files:
        p = os.path.join(HERE, f)
        if os.path.exists(p):
            h.update(open(p, "rb").read())
    return h.hexdigest()[:10]


def _visual_kinds(v):
    if "shots" in v:
        out = []
        for s in v["shots"]:
            out += _visual_kinds(s)
        return out
    for k in ("seg", "card", "real"):
        if k in v:
            return [k]
    return []


def generator_fingerprint(sc):
    """这一块的画面是由哪些源文件生成的 → 它们的内容哈希。

    ⛔⛔ 格子法的核心契约就在这一行：**漏登一个生成器文件，格子就会盖假章**。
       改了某一镜的建模、只要帧数没变，旧的「过」章还会原样生效。
       镜头函数每多拆出一个文件，就必须登进 config.json 的 shot_files（栽过两次）。
    """
    kinds = set(_visual_kinds(sc["visual"]))
    parts = []
    if "seg" in kinds:
        parts.append(_src_hash(*(C.SHOT_FILES + ["bl_charts.py", "bl_scene.py", "bl_lib.py"])))
    if "card" in kinds:
        parts.append(_src_hash("cards.py", "cards2.py"))
    if "real" in kinds:
        reals = sorted({x["real"] + ".py" for x in _flat(sc["visual"]) if "real" in x})
        parts.append(_src_hash(*reals))
    return "|".join(parts)


def _flat(v):
    if "shots" in v:
        out = []
        for s in v["shots"]:
            out += _flat(s)
        return out
    return [v]


def tts_path(sc):
    return os.path.join(FILM, "tts", sc["id"] + ".wav")


def visual_files(v):
    if "shots" in v:
        out = []
        for s in v["shots"]:
            out += visual_files(s)
        return out
    if "seg" in v:
        return ["../blender/seg/%s.mp4" % v["seg"]]
    if "card" in v:
        return ["cards/%s.png" % card_id(v["card"])]
    if "real" in v:
        return ["real/%s.mp4" % v["real"]]
    return []


def card_id(spec):
    return "c_" + hashlib.md5(repr(sorted(spec.items())).encode("utf-8")).hexdigest()[:8]


def product_exists(sc, layer):
    if layer == "稿":
        return True
    if layer == "画":
        return all(os.path.exists(os.path.join(FILM, f)) for f in visual_files(sc["visual"]))
    return os.path.exists(os.path.join(FILM, "clips_h", sc["id"] + ".mp4")) and os.path.exists(tts_path(sc))
