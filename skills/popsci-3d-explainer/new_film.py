# -*- coding: utf-8 -*-
"""起手式：把引擎和模板铺进一个新片目录。

    python new_film.py <新片目录> "<片名>"

做四件事：
  ① scripts/*.py 全量拷进新目录（引擎和片子放同一层，这样每个脚本的 HERE 就是片子目录）
  ② templates/ 里的 scenes.py / bl_shots.py / chapters.py / pauses_table.py 拷过去（已存在则跳过）
  ③ config.example.json → config.json，把 title 填好
  ④ 建 work/ 和 成品/

⛔ 引擎是**拷贝**不是引用：每部片都会按自己的题材改零件库和镜头，共享一份必然互相踩。
   改出通用的改进，再手工回流到 skill 里。
"""
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    if len(sys.argv) < 3:
        print(__doc__); return 1
    dst, title = os.path.abspath(sys.argv[1]), sys.argv[2]
    os.makedirs(dst, exist_ok=True)

    n = 0
    for f in sorted(os.listdir(os.path.join(HERE, "scripts"))):
        if f.endswith(".py"):
            shutil.copy2(os.path.join(HERE, "scripts", f), os.path.join(dst, f)); n += 1
    print("引擎 %d 个脚本 → %s" % (n, dst))

    for f in sorted(os.listdir(os.path.join(HERE, "templates"))):
        if not f.endswith(".py"):
            continue
        d = os.path.join(dst, f)
        if os.path.exists(d):
            print("  跳过已存在的 %s" % f); continue
        shutil.copy2(os.path.join(HERE, "templates", f), d)
        print("  模板 %s" % f)

    cfg = os.path.join(dst, "config.json")
    if os.path.exists(cfg):
        print("config.json 已存在，没动")
    else:
        j = json.load(open(os.path.join(HERE, "scripts", "config.example.json"), encoding="utf-8"))
        j["title"] = title
        j["script_md"] = "稿.md"
        json.dump(j, open(cfg, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print("config.json 写好（片名 %s）——先把 blender / 字体 / 配音三项改对" % title)

    for d in ("work", "成品"):
        os.makedirs(os.path.join(dst, d), exist_ok=True)

    print("""
下一步：
  1. 改 config.json：blender 路径、tts 后端、字体（少这三样跑不起来）
  2. 写 scenes.py（口播 + 分镜），然后
       python gen_gao.py && python check_scenes.py
  3. python make.py storyboard && python chain.py tts
  4. python chain.py audio      （插停顿 → 逐字对齐 → 出拍点）
  5. 照着 bl_shots.py 的两个示例把镜头写完，python check_beats_kw.py
  6. python chain.py render
  7. config.json 的 bgm.files 填几首曲子 → python bgm.py scan → python bgm.py mix <成片秒数>
  8. python chain.py post
完整流程和每一步的闸门见 SKILL.md。""")
    return 0


if __name__ == "__main__":
    sys.exit(main())
