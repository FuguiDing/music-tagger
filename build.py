# -*- coding: utf-8 -*-
"""一键打包（Windows 单文件 exe / macOS .app，含声纹兜底所需的 fpcalc 工具）。

用法:
    python build.py          # 自动按当前系统打包
产物:
    Windows: dist/MusicTagger.exe  ->  复制为项目根目录下的 音乐标签助手.exe
    macOS:   dist/MusicTagger.app  ->  dist/MusicTagger-macos.zip（M 系列与 Intel 通用）

声纹兜底依赖:
    tools/fpcalc(.exe)  Chromaprint 官方指纹工具（约 4MB，会被打进包，
                        运行时解压到临时目录使用）。没有它时依次尝试
                        系统 ffmpeg、Homebrew 的 fpcalc；都没有则声纹
                        通道只剩 Shazam。
准备 fpcalc:
    python tools/fetch_fpcalc.py       # 自动判断系统并下载（支持国内镜像）
    brew install libchromaprint        # macOS 也可这样装
"""

import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
IS_MAC = sys.platform == "darwin"
FPCALC = os.path.join(HERE, "tools", "fpcalc.exe" if os.name == "nt" else "fpcalc")
ICON_DIR = os.path.join(HERE, "assets")

# shazamio / aiohttp 是纯 Python + pydantic 数据类，PyInstaller 通常能自动
# 收集；shazamio_core 是 Rust 扩展，显式列出避免遗漏。
HIDDEN = [
    "shazamio", "shazamio_core", "aiohttp", "pydantic",
    "soundfile", "numpy",
    "mutagen.flac", "mutagen.wave", "mutagen.id3", "mutagen.mp4",
    "mutagen.apev2", "mutagen.oggvorbis", "mutagen.oggopus",
    "mutagen.wavpack", "mutagen.aiff",
]


def make_icns() -> str:
    """用 macOS 自带的 sips + iconutil 从 icon_256.png 生成 icon.icns。"""
    src = os.path.join(ICON_DIR, "icon_256.png")
    out = os.path.join(ICON_DIR, "icon.icns")
    if os.path.exists(out):
        return out
    if not (os.path.exists(src) and shutil.which("sips") and shutil.which("iconutil")):
        return ""
    iconset = os.path.join(HERE, "build", "icon.iconset")
    os.makedirs(iconset, exist_ok=True)
    sizes = [(16, "icon_16x16.png"), (32, "icon_16x16@2x.png"),
             (32, "icon_32x32.png"), (64, "icon_32x32@2x.png"),
             (128, "icon_128x128.png"), (256, "icon_128x128@2x.png"),
             (256, "icon_256x256.png"), (512, "icon_256x256@2x.png"),
             (512, "icon_512x512.png")]
    try:
        for px, name in sizes:
            subprocess.check_call(["sips", "-z", str(px), str(px), src,
                                   "--out", os.path.join(iconset, name)],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.check_call(["iconutil", "-c", "icns", iconset, "-o", out])
        return out
    except Exception:
        return ""


def main():
    py = sys.executable
    sep = os.pathsep

    cmd = [
        py, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--windowed",
        "--name", "MusicTagger",
        "--paths", HERE,
    ]
    if IS_MAC:
        # macOS 打 .app 包（--windowed + 默认 onedir）
        icns = make_icns()
        if icns:
            cmd += ["--icon", icns]
            print(">> 使用图标", os.path.basename(icns))
    else:
        cmd += ["--onefile"]
        icon = os.path.join(ICON_DIR, "icon.ico")
        if os.path.exists(icon):
            cmd += ["--icon", icon]

    for mod in HIDDEN:
        cmd += ["--hidden-import", mod]

    # 把图标资源打进包，运行时 _set_icon 才能找到
    for f in ("icon.ico", "icon_256.png"):
        p = os.path.join(ICON_DIR, f)
        if os.path.exists(p):
            cmd += ["--add-data", f"{p}{sep}assets"]

    if os.path.exists(FPCALC):
        # 打进包根目录，运行时 _MEIPASS/fpcalc(.exe)
        cmd += ["--add-binary", f"{FPCALC}{sep}."]
        print(">> 包含声纹工具", os.path.basename(FPCALC))
    else:
        print("!! 未找到 tools/fpcalc，声纹 AcoustID 引擎将依赖系统 ffmpeg / Homebrew")

    cmd.append(os.path.join(HERE, "main.py"))
    print(">>", " ".join(cmd))
    subprocess.check_call(cmd, cwd=HERE)

    if IS_MAC:
        app = os.path.join(HERE, "dist", "MusicTagger.app")
        if not os.path.isdir(app):
            raise SystemExit("打包失败：未生成 MusicTagger.app")
        base = os.path.join(HERE, "dist", "MusicTagger-macos")
        # 在 dist/ 内打包，zip 里是 MusicTagger.app/...
        shutil.make_archive(base, "zip",
                            root_dir=os.path.join(HERE, "dist"),
                            base_dir="MusicTagger.app")
        z = base + ".zip"
        print(f"\n完成: {z} ({os.path.getsize(z) / 1048576:.1f} MB)")
        print("提示: 未做公证（notarization），首次打开需右键 → 打开，"
              "或执行: xattr -cr MusicTagger.app")
    else:
        src = os.path.join(HERE, "dist", "MusicTagger.exe")
        dst = os.path.join(HERE, "音乐标签助手.exe")
        shutil.copy2(src, dst)
        print("\n完成:", dst, f"({os.path.getsize(dst) / 1048576:.1f} MB)")


if __name__ == "__main__":
    main()
