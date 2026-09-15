# -*- coding: utf-8 -*-
"""按文件路径显式加载所有镜头函数 → {"S11": func, ...}。

⛔⛔ **不许写 `import bl_shots`。** 上一部片的目录里往往有同名文件，而 sys.path 的顺序
   会被 bl_scene / bl_shots 自己的 insert 改好几道——曾经因此把上一部片的 14 镜量了进来、
   把本片的 35 镜全漏掉，而且不报任何错。一律用 importlib 按**绝对路径**加载。
"""
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import config as C  # noqa: E402


def load():
    out = {}
    for i, p in enumerate(C.shot_paths()):
        assert os.path.exists(p), "config.shot_files 里登记的文件不存在：" + p
        name = "_shots%d_%s" % (i, os.path.basename(p)[:-3])
        spec = importlib.util.spec_from_file_location(name, p)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
        out.update(getattr(mod, "SHOTS", {}))
    return out


def names():
    return sorted(load(), key=lambda s: int("".join(ch for ch in s if ch.isdigit()) or 0))
