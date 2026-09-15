# -*- coding: utf-8 -*-
"""全片唯一的「跟机器 / 跟片子有关」的配置入口。

除了这一份，其余脚本里不许再出现绝对路径、片名、字体名、曲名。
读取优先级：**环境变量 > 同目录 config.json > 下面的默认值**。

    import config as C
    C.BLENDER     blender.exe
    C.PY_AUDIO    装了 faster-whisper / soundfile / numpy 的那个 python
    C.TITLE       片名（成品文件名、storyboard.outfile 都从这儿来）
    C.SHOT_FILES  镜头函数散在哪几个文件里（指纹、闸门、调度全看这张表）

config.json 的完整字段见 reference/00-配置与依赖.md；起手直接
`copy config.example.json config.json` 再改三四行就能跑。
"""
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
_J = {}
_P = os.path.join(HERE, "config.json")
if os.path.exists(_P):
    _J = json.load(open(_P, encoding="utf-8"))


def get(key, default=None):
    """环境变量 POPSCI_<KEY> > config.json 的 <key> > default。"""
    v = os.environ.get("POPSCI_" + key.upper().replace(".", "_"))
    if v is not None:
        return v
    cur = _J
    for part in key.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def _first_exists(*cands):
    for c in cands:
        if c and os.path.exists(c):
            return c
    return None


# ---------- 片子 ----------
TITLE = get("title", "未命名")
OUTDIR = os.path.join(HERE, get("outdir", "成品"))          # 成片 / 封面 / 样片落在这儿
SCRIPT_MD = os.path.join(HERE, get("script_md", "稿.md"))   # gen_gao 写它，grid_script 读它
FPS = int(get("fps", 30))
CANVAS = tuple(get("canvas", [1920, 1080]))

FINAL_MP4 = os.path.join(OUTDIR, "%s_成片.mp4" % TITLE)
COVER_PNG = os.path.join(OUTDIR, "%s_封面.png" % TITLE)

# 镜头函数分布在哪几个文件里。
# ⛔⛔ 这张表是**格子法指纹的一部分**：漏登一个文件，改了那里的镜头、只要帧数没变，
#    旧的「过」章还会原样生效 —— 等于给新镜盖假章（0912/0913 各栽过一次）。
SHOT_FILES = list(get("shot_files", ["bl_shots.py"]))
SHOT_ENTRY = os.path.join(HERE, SHOT_FILES[0])              # blender -b --python <这个> -- S11 <outdir>

# ---------- 机器 ----------
BLENDER = get("blender") or _first_exists(
    r"C:\Program Files\Blender Foundation\Blender 4.5\blender.exe",
    r"C:\Program Files\Blender Foundation\Blender 4.4\blender.exe",
    r"C:\Program Files\Blender Foundation\Blender 4.2\blender.exe",
    "/Applications/Blender.app/Contents/MacOS/Blender",
    shutil.which("blender"))

# 跑 align.py / pauses.py / final_pass.py 的解释器：要有 faster-whisper、soundfile、numpy、librosa。
# 默认就是当前这个 python；单独建了 conda 环境就在 config.json 里写全路径。
PY_AUDIO = get("py_audio") or sys.executable
# 跑 build_video.py 的解释器（PIL / numpy 即可，通常和上面同一个）
PY_BUILD = get("py_build") or PY_AUDIO

WHISPER_MODEL = get("whisper_model", "large-v3")            # 本地目录或 HF 名字都行
WHISPER_DEVICE = get("whisper_device", "cuda")

# 废弃产物一律**搬**不删（红线）。默认放片子目录下，可指向全局回收站。
TRASH = get("trash") or os.path.join(HERE, "_废弃回收")
DISK_DRIVE = get("disk.drive", os.path.splitdrive(HERE)[0] + "\\")
DISK_MIN_GB = float(get("disk.min_gb", 40))

# ---------- 字体 ----------
FONT_UI = get("fonts.ui", r"C:\Windows\Fonts\msyhbd.ttc")        # 3D 标签 / 卡片
FONT_MONO = get("fonts.mono", r"C:\Windows\Fonts\consola.ttf")   # 终端视频
FONT_SUB_FILE = get("fonts.sub_file", r"C:\Windows\Fonts\STKAITI.TTF")
FONT_SUB_NAME = get("fonts.sub_name", "STKaiti")                 # libass 按字体**内部名**匹配，不是文件名
SUB_SIZE = int(get("fonts.sub_size", 60))

# ---------- 配音 ----------
# backend: "edge"（默认，免费云端，装 edge-tts 即可）| "voxcpm"（本地克隆，自己配模型和参考音）
TTS_BACKEND = get("tts.backend", "edge")
TTS_VOICE = get("tts.voice", "zh-CN-YunxiNeural")
TTS_RATE = get("tts.rate", "+8%")
TTS_TEMPO = float(get("tts.tempo", 1.0))     # 出声之后再 atempo 变速；VoxCPM 要 1.15 左右，edge 一般 1.0
TTS_PY = get("tts.python") or sys.executable         # voxcpm 专用环境
TTS_SCRIPT = get("tts.script")                       # voxcpm_tts.py 之类的外部脚本
TTS_MODEL = get("tts.model")
TTS_REF = get("tts.ref")                             # 克隆参考音 wav（同名 .txt 走 Ultimate Cloning）

# ---------- 音频目标 ----------
SEG_LUFS = float(get("audio.seg_lufs", -16.5))       # 单段 wav 对齐到这个响度
TARGET_LUFS = float(get("audio.target_lufs", -11.5))  # 成片响度
LIMIT = float(get("audio.limit", 0.88))              # alimiter 上限（真峰要 ≤ -0.3 dBFS）
BGM_V = float(os.environ.get("BGM_V", get("audio.bgm_v", 0.34)))
BGM_HP = os.environ.get("BGM_HP", str(get("audio.bgm_hp", 100)))
NOTCH = list(get("audio.notch", []))                 # 稳态哨音陷波中心，如 [299, 306]；量出来才填

# ---------- BGM ----------
BGM_LIB = get("bgm.lib", "")                         # 曲库根目录；空着就只用 bgm.files
BGM_SUBS = list(get("bgm.subs", [""]))               # 曲库里要扫的子目录
BGM_FILES = list(get("bgm.files", []))               # 直接给文件路径（不用曲库时走这条）
BGM_PICK = list(get("bgm.pick", []))                 # 定版曲单（文件名），空 = 按打分自动取前 N 首

# ---------- 字幕结构件 ----------
WATERMARK = get("watermark", "")                     # 防搬运水印文字，空 = 不打
SAMPLES = list(get("samples", []))                   # 样片清单 [{"name":"样片_开场","head":45}, {"name":"样片_厮杀","seg":"p02"}]


def assert_disk(min_gb=None):
    """开渲前必须量盘：一部 20 分钟的片帧序列要 30 GB 以上，盘满时 blender 每帧
    报 `No space left on device` 而计数不涨，光看日志会以为只是渲得慢。"""
    g = shutil.disk_usage(DISK_DRIVE).free / 1024 ** 3
    m = DISK_MIN_GB if min_gb is None else min_gb
    assert g >= m, "%s 只剩 %.1f GB（要 %.0f GB），先腾空间再渲" % (DISK_DRIVE, g, m)
    return g


def shot_paths():
    return [os.path.join(HERE, f) for f in SHOT_FILES]


def dump():
    print("片名      %s" % TITLE)
    print("成品      %s" % OUTDIR)
    print("blender   %s" % BLENDER)
    print("py_audio  %s" % PY_AUDIO)
    print("whisper   %s (%s)" % (WHISPER_MODEL, WHISPER_DEVICE))
    print("配音      %s / %s / tempo %.2f" % (TTS_BACKEND, TTS_VOICE, TTS_TEMPO))
    print("镜头文件  %s" % " ".join(SHOT_FILES))
    print("字幕字体  %s (%s) %d 号" % (FONT_SUB_NAME, FONT_SUB_FILE, SUB_SIZE))
    print("响度      段 %.1f / 成片 %.1f LUFS · BGM %.2f" % (SEG_LUFS, TARGET_LUFS, BGM_V))
    print("空间      %s 还剩 %.1f GB（下限 %.0f）" % (DISK_DRIVE, shutil.disk_usage(DISK_DRIVE).free / 1024 ** 3, DISK_MIN_GB))


if __name__ == "__main__":
    dump()
