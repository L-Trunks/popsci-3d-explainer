# -*- coding: utf-8 -*-
"""稿格子：一段一格，章绑段文本指纹。稿一改，章自动失效。

    python grid_script.py                     看格子状态
    python grid_script.py --过 p03 "理由"      盖章
    python grid_script.py --退 p07 "理由"      打回
    python grid_script.py --lint              机器可查的硬指标（字数/句长/术语/AI味）
"""
import hashlib, io, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import config as C  # noqa: E402

SRC = C.SCRIPT_MD                     # 由 gen_gao.py 从 scenes.py 反生成，改稿一律改 scenes.py
DB = os.path.join(HERE, "work", "grid_script.json")
RATE = float(C.get("speech_rate", 323))   # 净语速（字/分）。短视频约 320，长视频约 375


def segs():
    t = io.open(SRC, encoding="utf-8").read()
    out, cur, name = {}, [], None
    for line in t.split("\n"):
        # ⛔ 0912：段号从 p09 拆出了 p09b / p09c，`p\d+` 匹配不到字母后缀——
        #    它把三段都读成 p09、后一段覆盖前一段，于是 check_scenes 报「稿里没有 p09b/p09c」
        #    并且 p09 的正文成了 p09c 的。段号加后缀时这条正则必须跟着改。
        m = re.match(r"^【(p\d+[a-z]?)(.*)】\s*$", line)
        if m:
            if name:
                out[name] = ("\n".join(cur).strip(), title)
            name, title, cur = m.group(1), m.group(2).strip(), []
            continue
        if line.startswith("【画面】") or line.startswith(">") or line.startswith("#"):
            continue
        if name:
            cur.append(line)
    if name:
        out[name] = ("\n".join(cur).strip(), title)
    return out


def fp(s):
    return hashlib.md5(s.encode("utf-8")).hexdigest()[:12]


def load():
    return json.load(io.open(DB, encoding="utf-8")) if os.path.exists(DB) else {}


def save(d):
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    io.open(DB, "w", encoding="utf-8").write(json.dumps(d, ensure_ascii=False, indent=1))


def cn(s):
    return len(re.sub(r"[^一-鿿A-Za-z0-9]", "", s))


def show():
    S, d = segs(), load()
    ok = 0
    print("%-5s %-22s %5s %7s %-4s %s" % ("格", "标题", "字", "秒", "章", "理由"))
    for k, (body, title) in S.items():
        n = cn(body)
        st = d.get(k)
        good = st and st["fp"] == fp(body)
        ok += 1 if good else 0
        mark = "过" if good else ("失效" if st else "—")
        print("%-5s %-22s %5d %6.1f %-4s %s" % (k, title[:20], n, n / RATE * 60, mark, (st or {}).get("why", "")[:46]))
    tot = sum(cn(b) for b, _ in S.values())
    print("\n%d/%d 盖章 · 全片 %d 字 ≈ %.1f 分钟 @%.0f字/分" % (ok, len(S), tot, tot / RATE, RATE))


AI_SMELL = [
    (r"[：:]\s*$", "冒号腔（行末冒号）"),
    (r"答案是[：:]", "「答案是：」"),
    (r"[「」]", "书面引号"),
    (r"首先|其次|最后一点|第一步", "列举连词"),
    (r"值得注意的是|总之|综上", "AI 连接词"),
    (r"99%|百分之九十九的人", "伪量词"),
    (r"几千亿|几百万|几纳米|很多很多", "模糊量词"),
]
# 本片的「阻塞性名词」：观众不知道它就看不下去的那些词。
# 写在 config.json 的 terms 里；lint 会打印每个词**第一次出现在哪一段**——
# ⛔ 首现段和解释段不是同一段就是病（实测栽过：某术语首现在第 2 段、解释却在十五分钟后的第 8 段）。
TERMS = list(C.get("terms", []))


def lint():
    S = segs()
    bad = 0
    for k, (body, title) in S.items():
        msgs = []
        for pat, why in AI_SMELL:
            if re.search(pat, body, re.M):
                msgs.append("AI味:" + why)
        # 气口/字幕块：任意两个标点之间的连续run，超过 16 字字幕要断行、超过 20 字念着憋
        runs = [s for s in re.split(r"[。？！，、；：]", body) if cn(s) > 0]
        over = [s for s in runs if cn(s) > 20]
        if over:
            msgs.append("气口过长 %d 处（>20字）: %s…" % (len(over), over[0][:24]))
        q = body.count("？")
        if q > 3:
            msgs.append("问句 %d 个" % q)
        me = len(re.findall(r"我(?!们)", body))
        if me > 3:
            msgs.append("「我」%d 次" % me)
        n = cn(body)
        if n > 620:
            msgs.append("段过长 %d 字（>620）" % n)
        if msgs:
            bad += 1
            print("%-5s %s" % (k, " | ".join(msgs)))
    # 术语首现位置
    print("\n术语首现段：")
    for t in TERMS:
        first = next((k for k, (b, _) in S.items() if t in b), None)
        print("  %-6s %s" % (t, first or "未出现"))
    print("\nlint: %d/%d 段有提示" % (bad, len(S)))


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a:
        show()
    elif a[0] == "--lint":
        lint()
    elif a[0] in ("--过", "--退"):
        S, d = segs(), load()
        key = a[1]
        body = S[key][0]
        d[key] = {"fp": fp(body), "ok": a[0] == "--过", "why": a[2] if len(a) > 2 else ""}
        if a[0] == "--退":
            d.pop(key)
            d[key + "_退"] = {"why": a[2] if len(a) > 2 else ""}
        save(d)
        show()
