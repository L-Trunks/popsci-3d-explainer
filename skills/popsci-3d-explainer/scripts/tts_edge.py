# -*- coding: utf-8 -*-
"""默认配音后端：edge-tts（免费、云端、不要显卡、不要模型）。

    python tts_edge.py work/film/storyboard.json [--only p02,p05]

按 storyboard 逐段出 `work/film/tts/<段id>.wav`（48 kHz 单声道）。
音色/语速在 config.json 的 tts.voice / tts.rate 里改：
    zh-CN-YunxiNeural   男声，偏年轻，科普片常用
    zh-CN-YunjianNeural 男声，偏浑厚
    zh-CN-XiaoxiaoNeural 女声
    `python -m edge_tts --list-voices` 看全部

⛔ 读音覆盖 `{{显示|读音}}` 和高亮 `*词*` 的处理必须和 align.py / subs.py **完全一致**
   ——读的是读音侧，显示的是显示侧。这三处任一不一致，字幕就会整段错位。
⛔ 出完必须数 wav 数 == 段数（chain.py tts 里有这道 assert）。云端偶发丢句，缺的用 --only 补。

装：pip install edge-tts
"""
import asyncio
import json
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.stdout.reconfigure(encoding="utf-8")
import config as C  # noqa: E402

_OVR = re.compile(r"\{\{([^|{}]*)\|([^|{}]*)\}\}")


def to_tts(nar):
    """口播原文 → 真正念出去的那一串（取读音侧，去掉高亮标记）。"""
    return _OVR.sub(lambda m: m.group(2), nar).replace("*", "")


async def _say(text, mp3):
    import edge_tts
    await edge_tts.Communicate(text, C.TTS_VOICE, rate=C.TTS_RATE).save(mp3)


def main():
    sb = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "work", "film", "storyboard.json")
    only = None
    if "--only" in sys.argv:
        only = set(sys.argv[sys.argv.index("--only") + 1].split(","))
    cfg = json.load(open(sb, encoding="utf-8"))
    tdir = os.path.join(os.path.dirname(os.path.abspath(sb)), "tts")
    os.makedirs(tdir, exist_ok=True)

    for s in cfg["scenes"]:
        sid = s["id"]
        if only and sid not in only:
            continue
        text = to_tts(s.get("narration", "")).strip()
        if not text:
            print("!! %s 口播是空的，跳过" % sid); continue
        mp3 = os.path.join(tempfile.gettempdir(), "_tts_%s.mp3" % sid)
        asyncio.run(_say(text, mp3))
        out = os.path.join(tdir, sid + ".wav")
        af = ["-ar", "48000", "-ac", "1"]
        if abs(C.TTS_TEMPO - 1.0) > 1e-3:
            af = ["-filter:a", "atempo=%.3f" % C.TTS_TEMPO] + af
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", mp3] + af + [out], check=True)
        os.remove(mp3)
        d = float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries",
                                           "format=duration", "-of", "csv=p=0", out], text=True).strip())
        print("tts %-6s %6.2fs  %s" % (sid, d, text[:24]), flush=True)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
