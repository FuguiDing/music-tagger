# -*- coding: utf-8 -*-
"""下载 Chromaprint 官方指纹工具 fpcalc 到 tools/ 目录。

声纹兜底（AcoustID 引擎）需要它；不下载也能运行程序，只是该引擎不可用
（会回退到系统 ffmpeg / Homebrew 的 libchromaprint，都没有则只剩 Shazam）。

用法:
    python tools/fetch_fpcalc.py            # 自动判断当前系统
    python tools/fetch_fpcalc.py --windows  # 强制下载 Windows 版
    python tools/fetch_fpcalc.py --macos    # 强制下载 macOS 版（M 系列与 Intel 通用）

macOS 也可直接用 Homebrew 安装:  brew install libchromaprint
"""

import io
import os
import stat
import sys
import tarfile
import zipfile

VERSION = "1.6.2"

# chromaprint releases 提供的各平台预编译 fpcalc 包名
ASSETS = {
    "windows": f"chromaprint-fpcalc-{VERSION}-windows-x86_64.zip",
    "macos": f"chromaprint-fpcalc-{VERSION}-macos-universal.tar.gz",  # Intel + Apple Silicon
    "linux": f"chromaprint-fpcalc-{VERSION}-linux-x86_64.tar.gz",
}

MIRRORS = [
    "https://github.com/acoustid/chromaprint/releases/download/v{v}/{name}",
    # 国内网络访问 GitHub 直连常失败，准备几个公共镜像
    "https://ghproxy.net/https://github.com/acoustid/chromaprint/releases/download/v{v}/{name}",
    "https://gh-proxy.com/https://github.com/acoustid/chromaprint/releases/download/v{v}/{name}",
    "https://ghfast.top/https://github.com/acoustid/chromaprint/releases/download/v{v}/{name}",
]

HERE = os.path.dirname(os.path.abspath(__file__))
TARGET = os.path.join(HERE, "fpcalc.exe" if os.name == "nt" else "fpcalc")
MIN_SIZE = 100_000


def detect_platform() -> str:
    if sys.platform == "win32":
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


def download(name: str) -> bytes:
    import urllib.request

    last = None
    for tpl in MIRRORS:
        url = tpl.format(v=VERSION, name=name)
        try:
            print(">> 尝试", url.split("/")[-1], flush=True)
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = resp.read()
            ok_size = len(data) >= MIN_SIZE
            ok_fmt = zipfile.is_zipfile(io.BytesIO(data)) if name.endswith(".zip") \
                else tarfile.is_tarfile(io.BytesIO(data))
            if ok_size and ok_fmt:
                return data
            last = f"内容不完整（{len(data)} 字节）"
        except Exception as e:  # noqa: BLE001
            last = f"{type(e).__name__}: {e}"
            print("   失败:", last, flush=True)
    raise RuntimeError(f"全部下载源均失败：{last}")


def extract(data: bytes, out_path: str):
    if out_path.endswith(".exe"):  # Windows zip 包
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            member = next(n for n in z.namelist() if n.endswith("fpcalc.exe"))
            with z.open(member) as src, open(out_path, "wb") as dst:
                dst.write(src.read())
    else:  # macOS / Linux tar.gz 包
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as t:
            member = next(m for m in t.getmembers()
                          if m.isfile() and m.name.split("/")[-1] == "fpcalc")
            with t.extractfile(member) as src, open(out_path, "wb") as dst:
                dst.write(src.read())
        f = os.stat(out_path)
        os.chmod(out_path, f.st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    plat = arg.lstrip("-") if arg in ("--windows", "--macos", "--linux") \
        else detect_platform()

    if plat == "linux":
        print("Linux 建议直接用包管理器安装：sudo apt install libchromaprint-tools；"
              "脚本仍会尝试下载官方预编译包。")

    if os.path.exists(TARGET) and os.path.getsize(TARGET) > MIN_SIZE:
        print("已存在，跳过:", TARGET)
        return

    data = download(ASSETS[plat])
    extract(data, TARGET)
    print(f"完成: {TARGET} ({os.path.getsize(TARGET) / 1048576:.1f} MB)")


if __name__ == "__main__":
    sys.exit(main())
