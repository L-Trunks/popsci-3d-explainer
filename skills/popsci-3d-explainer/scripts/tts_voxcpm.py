# -*- coding: utf-8 -*-
"""可选配音后端：VoxCPM2 本地音色克隆（要显卡 + 模型 + 一段自己的参考音）。

    <装了 voxcpm 的 python> tts_voxcpm.py work/film/storyboard.json [--only p02] [--tempo 1.15]

config.json 里配：
    "tts": {"backend": "voxcpm", "python": "<那个环境的 python.exe>",
            "script": "<本文件的绝对路径>", "model": "<VoxCPM2 目录>",
            "ref": "<参考音 wav>", "tempo": 1.15}

为什么值得折腾（相对 edge-tts 的实测差别）：音高和本人真声完全吻合、字母缩写自然连读不断句、
原生 48 kHz。⛔ 但它有三个 edge-tts 没有的坑，**每一个都是静默的**：

⛔⛔ ① **长段落上会整段复读。** 实测一段 500 字的口播，从第 19 秒起把开头 19 秒原样又念了一遍。
   `check_read.py`（按拼音比、只报 ≤3 音节的 replace）**天生抓不到**——几十音节的整段重复
   是一个 insert，它给的还是 READ_OK。所以必须另跑 `check_dup.py`。
   修法：在 **tts_raw**（原始素材）上切掉重复段，刀口落在两个边界各自 ±0.30 秒里最安静的 20 ms。
⛔⛔ ② **跑完/中断后进程常不退**，攥着 6~10 GB 显存不放。下一次补跑抢不到显存会**静默退出**，
   `tts/` 里只有前 N 条，越补越死。排查要看 `nvidia-smi` 进程区的 `C` 类型行
   （别用 `tasklist | grep python` 数——管道编码问题会返回 0，误判成「进程已退」）。
⛔ ③ **语速跟参考音走，不吃 rate 参数**。实测只有 ~246 字/分，而讲解片基线是 322~375，
   一条 72 秒的片会被拖到 110 秒。所以出声之后统一 atempo 变速（tempo 1.15~1.44）。

参考音必须是**标准发音**：Ultimate Cloning 会照搬参考音的口音（平翘舌 shi→si 会被学走）。
同名 .txt 放参考音的文字稿就会走 Ultimate Cloning（最像本人），没有就退化成 Controllable。
⛔ 参考音本身的音色缺陷会带进每一段（实测胸腔比 +9.2 dB = 低频厚），能在最后一次混音里
   修的就别回头改素材层——见 final_pass.audio_graph。
"""
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.stdout.reconfigure(encoding="utf-8")
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
import config as C  # noqa: E402

_OVR = re.compile(r"\{\{([^|{}]*)\|([^|{}]*)\}\}")


def to_tts(nar):
    return _OVR.sub(lambda m: m.group(2), nar).replace("*", "")


def main():
    import soundfile as sf
    from voxcpm import VoxCPM

    sb = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "work", "film", "storyboard.json")
    only = set(sys.argv[sys.argv.index("--only") + 1].split(",")) if "--only" in sys.argv else None
    tempo = float(sys.argv[sys.argv.index("--tempo") + 1]) if "--tempo" in sys.argv else C.TTS_TEMPO
    seeds = [int(x) for x in sys.argv[sys.argv.index("--seed") + 1].split(",")] if "--seed" in sys.argv else [42]

    cfg = json.load(open(sb, encoding="utf-8"))
    tdir = os.path.join(os.path.dirname(os.path.abspath(sb)), "tts")
    os.makedirs(tdir, exist_ok=True)

    ref = C.TTS_REF
    assert ref and os.path.exists(ref), "config.tts.ref 要指向一段参考音 wav"
    ref_txt = os.path.splitext(ref)[0] + ".txt"
    ptext = open(ref_txt, encoding="utf-8").read().strip() if os.path.exists(ref_txt) else ""

    model = VoxCPM.from_pretrained(C.TTS_MODEL, load_denoiser=False)
    sr = model.tts_model.sample_rate
    print("VoxCPM loaded, sr=%d, ultimate=%s" % (sr, bool(ptext)), flush=True)

    for s in cfg["scenes"]:
        sid = s["id"]
        if only and sid not in only:
            continue
        text = to_tts(s.get("narration", "")).strip()
        if not text:
            continue
        for seed in seeds:
            kw = dict(text=text, reference_wav_path=ref, cfg_value=2.0, inference_timesteps=10, seed=seed)
            if ptext:
                kw.update(prompt_wav_path=ref, prompt_text=ptext)
            wav = model.generate(**kw)
            out = os.path.join(tdir, sid + ("_s%d" % seed if len(seeds) > 1 else "") + ".wav")
            sf.write(out, wav, sr)
            raw = len(wav) / sr
            if abs(tempo - 1.0) > 1e-3:
                tmp = out + ".raw.wav"
                os.replace(out, tmp)
                subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", tmp, "-filter:a", "atempo=%.3f" % tempo, out], check=True)
                os.remove(tmp)
                raw /= tempo
            print("tts %-6s seed=%d %6.2fs  %s" % (sid, seed, raw, text[:22]), flush=True)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
