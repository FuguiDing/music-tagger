# -*- coding: utf-8 -*-
"""一键打包为单文件 exe（含声纹兜底所需的 fpcalc 工具）。

用法:
    python build.py
产物:
    dist/MusicTagger.exe  ->  自动复制为项目根目录下的 音乐标签助手.exe

声纹兜底依赖:
    tools/fpcalc.exe   Chromaprint 官方指纹工具（约 4MB，会被打进 exe，
                       运行时解压到临时目录使用）。若没有它，会尝试
                       回退到系统 ffmpeg；两者都没有则声纹通道不可用。
"""

import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
FPCALC = os.path.join(HERE, "tools", "fpcalc.exe")

# shazamio / aiohttp 是纯 Python + pydantic 数据类，PyInstaller 通常能自动
# 收集；shazamio_core 是 Rust 扩展，显式列出避免遗漏。
HIDDEN = [
    "shazamio", "shazamio_core", "aiohttp", "pydantic",
    "soundfile", "numpy",
    "mutagen.flac", "mutagen.wave", "mutagen.id3", "mutagen.mp4",
    "mutagen.apev2", "mutagen.oggvorbis", "mutagen.oggopus",
    "mutagen.wavpack", "mutagen.aiff",
]


def main():
    py = sys.executable
    icon = os.path.join(HERE, "assets", "icon.ico")
    if not os.path.exists(icon):
        subprocess.check_call([py, os.path.join(HERE, "gen_icon.py")])

    cmd = [
        py, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--onefile", "--windowed",
        "--name", "MusicTagger",
        "--paths", HERE,
    ]
    for mod in HIDDEN:
        cmd += ["--hidden-import", mod]
    if os.path.exists(FPCALC):
        # 打进包根目录，运行时 _MEIPASS/fpcalc.exe
        cmd += ["--add-binary", f"{FPCALC}{os.pathsep}."]
        print(">> 包含声纹工具 fpcalc.exe")
    else:
        print("!! 未找到 tools/fpcalc.exe，声纹通道将依赖系统 ffmpeg")
    if os.path.exists(icon):
        cmd += ["--icon", icon]
    cmd.append(os.path.join(HERE, "main.py"))

    print(">>", " ".join(cmd))
    subprocess.check_call(cmd, cwd=HERE)

    src = os.path.join(HERE, "dist", "MusicTagger.exe")
    dst = os.path.join(HERE, "音乐标签助手.exe")
    shutil.copy2(src, dst)
    print("\n完成:", dst, f"({os.path.getsize(dst) / 1048576:.1f} MB)")


if __name__ == "__main__":
    main()
