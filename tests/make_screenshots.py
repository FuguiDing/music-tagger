# -*- coding: utf-8 -*-
"""生成 README 用的界面截图（真实扫描 + 匹配后的画面）。

用法:
    python tests/make_screenshots.py
产物:
    docs/screenshot-main.png     主界面
    docs/screenshot-acoustic.png 声纹设置对话框
"""

import ctypes
import ctypes.wintypes as wt
import os
import shutil
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

from PIL import Image  # noqa: E402

from mtcore.app import App  # noqa: E402

# 演示目录放在公共区（不含用户名），这样截图可直接用于 README
WORK = r"C:\Users\Public\Music\TaggerDemo"
SAMPLES = os.path.join(ROOT, "tests", "_samples")
OUT = os.path.join(ROOT, "docs")


def grab(hwnd, path):
    rc = wt.RECT()
    ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rc))
    w, h = rc.right - rc.left, rc.bottom - rc.top
    hdc = ctypes.windll.user32.GetWindowDC(hwnd)
    mem = ctypes.windll.gdi32.CreateCompatibleDC(hdc)
    bmp = ctypes.windll.gdi32.CreateCompatibleBitmap(hdc, w, h)
    ctypes.windll.gdi32.SelectObject(mem, bmp)
    ctypes.windll.user32.PrintWindow(hwnd, mem, 2)

    class BMIH(ctypes.Structure):
        _fields_ = [("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_int32),
                    ("biHeight", ctypes.c_int32), ("biPlanes", ctypes.c_uint16),
                    ("biBitCount", ctypes.c_uint16), ("biCompression", ctypes.c_uint32),
                    ("biSizeImage", ctypes.c_uint32), ("biXPelsPerMeter", ctypes.c_int32),
                    ("biYPelsPerMeter", ctypes.c_int32), ("biClrUsed", ctypes.c_uint32),
                    ("biClrImportant", ctypes.c_uint32)]

    info = BMIH()
    info.biSize = ctypes.sizeof(BMIH)
    info.biWidth, info.biHeight = w, -h
    info.biPlanes, info.biBitCount, info.biCompression = 1, 32, 0
    buf = ctypes.create_string_buffer(w * h * 4)
    ctypes.windll.gdi32.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(info), 0)
    Image.frombuffer("RGB", (w, h), buf, "raw", "BGRX", 0, 1).save(path)
    ctypes.windll.user32.ReleaseDC(hwnd, hdc)
    ctypes.windll.gdi32.DeleteObject(bmp)
    ctypes.windll.gdi32.DeleteDC(mem)
    return w, h


def pump(app, seconds):
    end = time.time() + seconds
    while time.time() < end:
        app.update()
        time.sleep(0.04)


def pump_until_idle(app, limit=180):
    end = time.time() + limit
    while time.time() < end:
        app.update()
        time.sleep(0.05)
        if not app.busy:
            pump(app, 0.6)
            return True
    return False


def main():
    os.makedirs(OUT, exist_ok=True)
    if not os.path.isdir(WORK) or not os.listdir(WORK):
        os.makedirs(WORK, exist_ok=True)
        for f in os.listdir(SAMPLES):
            shutil.copy(os.path.join(SAMPLES, f), os.path.join(WORK, f))
        print("已复制示例音频到", WORK)
    app = App()
    app.var_folder.set(WORK)
    app.var_auto.set(False)      # 截图里保留「待写入」状态更直观
    app.var_acoustic.set(True)
    pump(app, 0.6)

    app.start_scan()
    pump_until_idle(app, 30)
    print("扫描完成，行数:", len(app.rows))

    app.start_match()
    ok = pump_until_idle(app, 240)
    print("匹配完成" if ok else "匹配超时", "，行数:", len(app.rows))

    wid = int(app.winfo_id())
    hwnd = ctypes.windll.user32.GetParent(wid) or wid
    print("主窗口尺寸:", grab(hwnd, os.path.join(OUT, "screenshot-main.png")))

    app.show_acoustic_settings()
    pump(app, 1.0)
    dlg = ctypes.windll.user32.FindWindowW(None, "声纹兜底设置")
    if dlg:
        print("对话框尺寸:", grab(dlg, os.path.join(OUT, "screenshot-acoustic.png")))
    else:
        print("未找到对话框窗口")
    app.destroy()
    print("完成 →", OUT)


if __name__ == "__main__":
    main()
