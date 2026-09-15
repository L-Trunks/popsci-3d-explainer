# -*- coding: utf-8 -*-
"""从 scenes.py（单一事实源）反向生成口播稿 markdown。

    python gen_gao.py

⛔⛔ **稿不是手写的，是从分镜反生成的。** 只有一个事实源（scenes.py），
   稿只是给人读、给稿格子盖章、给 check_scenes 做比对的投影。
⛔ `check_scenes.py` 拿 scenes.py 和这份稿**逐字**比——改了 scenes.py 就必须重跑这个，
   否则闸门会报「分镜和稿不一致」，而且是在渲染前一刻才报。
"""
import io, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import config as C  # noqa: E402
from scenes import SCENES  # noqa: E402

try:
    from chapters import SEC        # {段id: 小节名}，和字幕 HUD 共用同一张表
except ImportError:
    SEC = {}


def disp(t):
    return re.sub(r"\{\{([^|{}]*)\|[^|{}]*\}\}", r"\1", t).replace("*", "")


def kind(sh):
    if "seg" in sh:
        return "3D " + sh["seg"]
    if "real" in sh:
        return "实测 " + sh["real"]
    c = sh["card"]
    return "卡片 " + c.get("type", "?") + (("·" + c.get("kind", "")) if c.get("kind") else "")


out = ["# 《%s》口播稿（由 scenes.py 反生成，不要手改这份文件）" % C.TITLE,
       "",
       "> 读音覆盖写法 `{{显示|读音}}`：只换读法、不换显示，字幕和稿都不受影响。",
       "> 【画面】行给分镜：3D = Blender 建模镜头；卡片 = PIL 出的深色图；实测 = 本机录屏。",
       "> 一镜一个主角、只有主角发光；标签出现帧 = 关键词说出的那一帧。",
       ""]
for sc in SCENES:
    t = SEC.get(sc["id"], "")
    out.append("【%s%s】" % (sc["id"], (" " + t) if t else ""))
    out.append(disp(sc["narration"]))
    out.append("【画面】" + " → ".join(kind(x) for x in sc["visual"]["shots"]))
    out.append("")
io.open(C.SCRIPT_MD, "w", encoding="utf-8").write("\n".join(out))
print("%s 写好，%d 段" % (os.path.basename(C.SCRIPT_MD), len(SCENES)))
