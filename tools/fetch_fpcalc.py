# -*- coding: utf-8 -*-
"""下载 Chromaprint 官方指纹工具 fpcalc.exe 到 tools/ 目录。

声纹兜底（AcoustID 引擎）需要它；不下载也能运行程序，只是该引擎不可用
（会回退到系统 ffmpeg，两者都没有则只剩 Shazam 可用）。

用法:
    python tools/fetch_fpcalc.py
"""

import io
import os
import sys
import zipfile

URLS = [
    "https://github.com/acoustid/chromaprint/releases/download/v1.6.2/"
    "chromaprint-fpcalc-1.6.2-windows-x86_64.zip",
    # 国内网络访问 GitHub 直连常失败，准备几个公共镜像
    "https://ghproxy.net/https://github.com/acoustid/chromaprint/releases/download/"
    "v1.6.2/chromaprint-fpcalc-1.6.2-windows-x86_64.zip",
    "https://gh-proxy.com/https://github.com/acoustid/chromaprint/releases/download/"
    "v1.6.2/chromaprint-fpcalc-1.6.2-windows-x86_64.zip",
    "https://ghfast.top/https://github.com/acoustid/chromaprint/releases/download/"
    "v1.6.2/chromaprint-fpcalc-1.6.2-windows-x86_64.zip",
]

HERE = os.path.dirname(os.path.abspath(__file__))
TARGET = os.path.join(HERE, "fpcalc.exe")
MIN_SIZE = 100_000


def download() -> bytes:
    import urllib.request

    last = None
    for url in URLS:
        try:
            print(">> 尝试", url.split("/")[-1][:40], "…", flush=True)
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = resp.read()
            if len(data) >= MIN_SIZE and zipfile.is_zipfile(io.BytesIO(data)):
                return data
            last = f"内容不完整（{len(data)} 字节）"
        except Exception as e:  # noqa: BLE001
            last = f"{type(e).__name__}: {e}"
            print("   失败:", last, flush=True)
    raise RuntimeError(f"全部下载源均失败：{last}")


def main():
    if os.path.exists(TARGET) and os.path.getsize(TARGET) > MIN_SIZE:
        print("已存在，跳过:", TARGET)
        return
    if os.name != "nt":
        print("此脚本只为 Windows 准备 fpcalc.exe；Linux/macOS 请用包管理器安装 "
              "libchromaprint-tools / chromaprint。")
        return

    data = download()
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        name = next((n for n in z.namelist() if n.endswith("fpcalc.exe")), None)
        if not name:
            raise RuntimeError("压缩包里没有 fpcalc.exe")
        with z.open(name) as src, open(TARGET, "wb") as dst:
            dst.write(src.read())

    print(f"完成: {TARGET} ({os.path.getsize(TARGET) / 1048576:.1f} MB)")


if __name__ == "__main__":
    sys.exit(main())
