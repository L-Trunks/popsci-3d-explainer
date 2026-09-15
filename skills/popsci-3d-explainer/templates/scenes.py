# -*- coding: utf-8 -*-
"""分镜契约 = 这部片的**单一事实源**。口播和画面写在一起，稿由它反生成。

一段 = 一条 wav（一次 TTS、一次对齐、一格「稿」和一格「段」）。
段内按**块**切画面：一块 = 一个镜头 = 一格「画」。

⛔ 块的前 4 个字里不要放 {{}} 或 *（shots.at 取前 4 字当定位关键词）。
⛔ 同一个 seg / real 不许出现两次（镜头零复用；重复会让后一块覆盖前一块的 beats，
   那一镜只渲一小段）。
⛔ 一个 seg 只对应一个块。
读音覆盖 `{{显示|读音}}`：只改读法、不改显示。写法见 reference/02-配音与对齐.md。
"""


def _key(txt, n=4):
    import re as _re
    t = _re.sub(r"\{\{([^|{}]*)\|[^|{}]*\}\}", r"\1", txt).replace("*", "")
    return t[:n]


def _disp_len(txt):
    import re as _re
    return len(_re.sub(r"\{\{([^|{}]*)\|[^|{}]*\}\}", r"\1", txt).replace("*", ""))


def P(pid, chunks):
    """把 [(口播片段, 画面), ...] 拼成一段：自动算每块的定位关键词 at 和字符偏移 off。"""
    nar = "".join(c for c, _ in chunks)
    shots = []; off = 0
    for c, v in chunks:
        v = dict(v); v["at"] = _key(c); v["off"] = off; off += _disp_len(c); shots.append(v)
    return dict(id=pid, narration=nar, visual={"shots": shots})


# ============================ 卡片 ============================
# 卡片是 cards.py / cards2.py 出的深色 PNG。⛔ 能用建模就别用卡片：
#    纯文本画面占比压到 5% 以下是硬指标（第一版 18.6% 被判「像 PPT」）。
C_HELLO = {"type": "title", "title": "这期讲透三件事", "sub": "① … · ② … · ③ …"}
C_BIG = {"type": "number", "big": "2750 亿", "unit": "口井", "caption": "一根内存条里的格子数"}


# ============================ 段 ============================
# 一段 150~620 字。>620 字的段 TTS 容易整段复读（见 tts_voxcpm.py 的坑①）。
SCENES = [

    P("p01", [
        # (口播片段, 画面)。画面三选一：
        #   {"seg": "S01a"}        Blender 镜头（函数名 S01，段名 S01a）
        #   {"card": C_HELLO}      卡片
        #   {"real": "bench"}      实测录屏（要有同名的 bench.py 生成器）
        ("先看一个数字：这东西一年涨了四倍。", {"seg": "S01a"}),
        ("但问题来了，它凭什么？", {"seg": "S02a"}),
        ("这期讲透三件事。", {"card": C_HELLO}),
    ]),

    P("p02", [
        ("这是第二段的第一块。", {"seg": "S03a"}),
        ("再往下看，就是第二块了。", {"seg": "S04a"}),
    ]),

]


# ============================ 静默片尾 ============================
# ⛔⛔ 片尾**不进 SCENES**：SCENES 里的段一定会被 TTS 走一遍，narration 空了
#    durs 会记成 missing、align 的闸门直接挂。所以写成下面这两个变量，
#    由 final_pass.tail() 拼成一段无声视频接在正片后面。BGM 照常往下走。
TAIL_DUR = 7.0
# ⛔ 这两张卡的 items 是**会被渲染出来的正文**，别把 ⛔ / ✅ 这类记号写进去：
#    卡片用 config.fonts.ui（默认微软雅黑）画，没有这些字形，成片上就是一个豆腐块。
#    0914 实测踩过。要给自己留提示就写在这儿的注释里。
# ⛔ 别在卡上放长链接——观众记不住也点不了，链接留给简介。
TAIL_CARDS = [
    {"type": "bullets", "title": "数据出处", "items": [
        "每个数字的算法或链接都写在 数据出处.md",
        "片中所有数字均可复算",
    ]},
    {"type": "bullets", "title": "音乐 · 制作", "items": [
        "*BGM*：曲名一行一首（CC-BY 的必须署名）",
        "画面全部自建模，无外部素材",
        "配音：写清用的是哪个 TTS 或音色",
    ]},
]
