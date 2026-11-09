# -*- coding: utf-8 -*-
"""验证打包后的 exe：fpcalc 解压、声纹引擎状态、界面截图。"""

import ctypes
import ctypes.wintypes as wt
import glob
import os
import subprocess
import sys
import time

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "exe2_shot.png")
EXE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "音乐标签助手_声纹版.exe")

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

proc = subprocess.Popen([EXE])
print("pid:", proc.pid)

# 等待 onefile 解包完成
fpcalc_found = ""
for _ in range(60):
    for d in glob.glob(os.path.join(os.environ.get("TEMP", ""), "_MEI*")):
        p = os.path.join(d, "fpcalc.exe")
        if os.path.exists(p):
            fpcalc_found = p
            break
    if fpcalc_found:
        break
    time.sleep(0.5)
print("fpcalc in _MEIPASS:", fpcalc_found,
      os.path.getsize(fpcalc_found) // 1024 if fpcalc_found else "")

time.sleep(4)

# 找窗口并截图
hwnd = ctypes.windll.user32.FindWindowW(None, "音乐标签助手 · 网易云 / QQ音乐元数据匹配")
print("hwnd:", hwnd)
if hwnd:
    rc = wt.RECT()
    ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rc))
    w, h = rc.right - rc.left, rc.bottom - rc.top

    class BMIH(ctypes.Structure):
        _fields_ = [("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_int32),
                    ("biHeight", ctypes.c_int32), ("biPlanes", ctypes.c_uint16),
                    ("biBitCount", ctypes.c_uint16), ("biCompression", ctypes.c_uint32),
                    ("biSizeImage", ctypes.c_uint32), ("biXPelsPerMeter", ctypes.c_int32),
                    ("biYPelsPerMeter", ctypes.c_int32), ("biClrUsed", ctypes.c_uint32),
                    ("biClrImportant", ctypes.c_uint32)]

    hdc = ctypes.windll.user32.GetWindowDC(hwnd)
    mem = ctypes.windll.gdi32.CreateCompatibleDC(hdc)
    bmp = ctypes.windll.gdi32.CreateCompatibleBitmap(hdc, w, h)
    ctypes.windll.gdi32.SelectObject(mem, bmp)
    ctypes.windll.user32.PrintWindow(hwnd, mem, 2)
    info = BMIH()
    info.biSize = ctypes.sizeof(BMIH)
    info.biWidth, info.biHeight = w, -h
    info.biPlanes, info.biBitCount, info.biCompression = 1, 32, 0
    buf = ctypes.create_string_buffer(w * h * 4)
    ctypes.windll.gdi32.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(info), 0)
    from PIL import Image
    img = Image.frombuffer("RGB", (w, h), buf, "raw", "BGRX", 0, 1)
    img.save(OUT)
    print("saved:", OUT, img.size)

proc.terminate()
