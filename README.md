# popsci-3d-explainer

**用 Blender 无界面渲染做 10–25 分钟横版 3D 科普长片的一条完整管线**，装成一个 Claude Code skill。
口播定稿 → 配音 → 逐字对齐 → 按每个关键词说出的那一帧渲染 3D 镜头 → 章节结构件 → 混音 → 逐格验收。

> *A Claude Code skill and script set for producing long-form (10–25 min) 3D science explainer videos:
> script → TTS → word-level alignment → beat-driven headless Blender renders → chapter HUD → mix → per-shot review.
> English summary: [README.en.md](README.en.md)*

适合「拆开讲原理」的题材：硬件、半导体、机械、物理机制——需要剖切动画、需要观众看见里面是怎么动的。
不适合竖版快剪和实拍空镜蒙太奇。

这条管线跑通了两部成片：《固态硬盘》（9 分 47 秒）和《内存与 HBM》（22 分钟，108 个镜头，3.8 万帧）。
3D 镜头全部由 Python 脚本在 Blender 里建模渲染；《内存与 HBM》除了数据卡片和一段实测，没有用任何外部素材。

---

## 成片预览

**《内存与 HBM》40 秒片段**（配音、字幕、章节 HUD、进度条、BGM 都是管线一次总装出来的）

https://github.com/user-attachments/assets/924b2fcf-5adb-4524-aea1-05327c4e5e0d

**完整版在 B 站**（点封面播放）

<table>
<tr>
<td width="50%"><a href="https://www.bilibili.com/video/BV1gdYr6QEMg/"><img src="docs/assets/bili-memory.jpg" alt="内存为什么涨价？"></a></td>
<td width="50%"><a href="https://www.bilibili.com/video/BV135Yu6hEbH/"><img src="docs/assets/bili-ssd.jpg" alt="固态硬盘的工作原理"></a></td>
</tr>
<tr>
<td align="center">《内存为什么涨价？》22:36</td>
<td align="center">《固态硬盘的工作原理》9:48</td>
</tr>
</table>

下面几张是片中镜头的无声动图。

**HBM 一层层叠起来**

![](docs/assets/hbm-stack.gif)

**电子被灌进浮栅的「笼子」**

![](docs/assets/ssd-cage.gif)

**拍点驱动**：先有配音和逐字时间戳，动画元素在对应的字说出来时出现

![](docs/assets/beat-sync.gif)

---

## 流水线

⛔ 一条铁律：**先声音，后画面**。时间轴由配音决定，不是由分镜估出来的。

| # | 做什么 | 命令 | 闸门 |
|---|---|---|---|
| 1 | 写口播 + 分镜 | 手写 `scenes.py` | 一段 150~620 字；一块 ≤16 字 |
| 2 | 反生成稿 | `python gen_gao.py` | — |
| 3 | 稿格子 + lint | `python grid_script.py --lint` | AI 味 / 气口 / 术语首现 |
| 4 | 分镜闸门 | `python check_scenes.py` | CHECK_OK：稿与分镜逐字一致 |
| 5 | 出 storyboard | `python make.py storyboard` | 改稿后第一件事 |
| 6 | 配音 | `python chain.py tts` | wav 数 == 段数 |
| 7 | 音频链 | `python chain.py audio` | 插停顿 → 逐字对齐 → 出拍点 |
| 8 | 写镜头 | 手写 `bl_shots.py` | `python check_beats_kw.py` → KW_OK |
| 9 | 渲染 | `python chain.py render` | 磁盘空间闸门；日志无 `LABEL_` |
| 10 | 总装 | `python bgm.py scan` / `mix <秒数>` → `python chain.py post` | 封面 + 字幕 + 章节卡 / HUD / 进度条 + BGM |
| 11 | 验收 | `python grid.py` + `python verify.py` | 三层格子全满 + VERIFY_OK |

只改字幕或 BGM、画面没动时：`python final_pass.py final`（约 1 分钟）或 `remix`（约 15 秒）。

每一步的细节、判据和踩过的坑在 `skills/popsci-3d-explainer/reference/` 下九份文档里，按环节读：

| 文档 | 内容 |
|---|---|
| `00-配置与依赖.md` | 安装、`config.json` 全字段 |
| `01-文案与分镜.md` | scenes.py 写法、读音覆盖、英文怎么写 |
| `02-配音与对齐.md` | 插停顿、逐字对齐、拍点、回读检查 |
| `03-建模与镜头.md` | 取景 / 布光 / 曝光 / 字色自动化、标签排版、并行渲染 |
| `04-字幕与结构件.md` | 断句、章节卡、HUD、进度条、封面 |
| `05-混音与BGM.md` | 选曲、响度与真峰、陷波 |
| `06-验收与格子法.md` | 三层格子、指纹、verify 十二条 |
| `07-坑册.md` | 所有静默失败的地方 |
| `08-改稿与插入式新增.md` | 接修改意见、插入新段、帧已清时在正片上删段 |

---

## 安装

```bash
git clone https://github.com/L-Trunks/popsci-3d-explainer.git
cd popsci-3d-explainer
bash install.sh            # Windows: powershell -ExecutionPolicy Bypass -File install.ps1
```

装到 `~/.claude/skills/`；加 `--project`（Windows 用 `-Project`）只装到当前项目。
装好后跟 Claude Code 说「做一支 3D 讲解片」就会触发。

不用 Claude 也能跑：脚本都是普通 Python，照 `SKILL.md` 的十一步手动执行即可。

## 起手

```bash
python ~/.claude/skills/popsci-3d-explainer/new_film.py path/to/我的新片 "片名"
cd path/to/我的新片
# 改 config.json：blender 路径、tts 后端、字体
python config.py           # 打印解析结果，确认路径都对
```

`new_film.py` 把引擎脚本和模板**拷贝**进片子目录（不是共享引用）——每部片都会按题材改零件库和镜头。
模板自带一个 2 段 4 镜的最小示例，改完 `config.json` 可以直接从第 2 步跑到第 10 步。

---

## 依赖

| 东西 | 说明 |
|---|---|
| Blender 4.5+ | EEVEE Next，只用命令行 `-b` |
| ffmpeg / ffprobe | 需在 PATH 里 |
| Python 3.10+ | `pip install numpy soundfile pillow jieba pypinyin edge-tts faster-whisper` |
| 可选 | `librosa`（BGM 自动打分）、`matplotlib`（实测图表） |
| 可选 · 配音 | 默认 edge-tts（免费）；想用自己的声音可接 [VoxCPM](https://github.com/OpenBMB/VoxCPM) 本地克隆，坑写在 `tts_voxcpm.py` 文件头 |
| GPU | 12 GB 显存够用；逐字对齐用 CUDA 快，CPU 也能跑 |
| 磁盘 | 一部 20 分钟的片，帧序列约 32 GB |

在 **Windows 11** 上跑通。Linux / macOS 需要改字体路径和 Blender 候选路径（见 `00-配置与依赖.md` 末尾）。

---

## 致谢

- https://github.com/Vincentwei1021/anything2explainer

## 许可

- 代码（`skills/popsci-3d-explainer/scripts/`、`templates/`、`new_film.py`、安装脚本）：MIT
- 文档（`SKILL.md`、`reference/`、README、`docs/`）：CC BY 4.0

详见 [LICENSE](LICENSE)。

作者：特兰克斯（[@L-Trunks](https://github.com/L-Trunks)）
