# -*- coding: utf-8 -*-
"""启动打包后的 exe，截图验证后关闭。"""

import ctypes
import ctypes.wintypes as wt
import os
import subprocess
import sys
import time

ctypes.windll.shcore.SetProcessDpiAwareness(2)
from PIL import ImageGrab

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXE = os.path.join(HERE, "音乐标签助手.exe")
OUT = os.path.join(HERE, "tests", "exe_shot.png")

proc = subprocess.Popen([EXE])
title = "音乐标签助手 · 网易云 / QQ音乐元数据匹配"
hwnd = 0
deadline = time.time() + 30
while time.time() < deadline:
    hwnd = ctypes.windll.user32.FindWindowW(None, title)
    if hwnd:
        break
    time.sleep(0.3)
print("hwnd:", hwnd, "pid:", proc.pid)
if hwnd:
    time.sleep(2.5)
    rc = wt.RECT()
    ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rc))
    w, h = rc.right - rc.left, rc.bottom - rc.top
    img = ImageGrab.grab(bbox=(rc.left, rc.top, rc.right, rc.bottom))
    # 用 PrintWindow 重抓，避免被其他窗口遮挡
    try:
        import ctypes as c

        class BMIH(ctypes.Structure):
            _fields_ = [("biSize", c.c_uint32), ("biWidth", c.c_int32),
                        ("biHeight", c.c_int32), ("biPlanes", c.c_uint16),
                        ("biBitCount", c.c_uint16), ("biCompression", c.c_uint32),
                        ("biSizeImage", c.c_uint32), ("biXPelsPerMeter", c.c_int32),
                        ("biYPelsPerMeter", c.c_int32), ("biClrUsed", c.c_uint32),
                        ("biClrImportant", c.c_uint32)]

        hdc = c.windll.user32.GetWindowDC(hwnd)
        mem = c.windll.gdi32.CreateCompatibleDC(hdc)
        bmp = c.windll.gdi32.CreateCompatibleBitmap(hdc, w, h)
        c.windll.gdi32.SelectObject(mem, bmp)
        ok = c.windll.user32.PrintWindow(hwnd, mem, 2)  # PW_RENDERFULLCONTENT
        bmpinfo = BMIH()
        bmpinfo.biSize = ctypes.sizeof(BMIH)
        bmpinfo.biWidth = w
        bmpinfo.biHeight = -h
        bmpinfo.biPlanes = 1
        bmpinfo.biBitCount = 32
        bmpinfo.biCompression = 0
        buf = ctypes.create_string_buffer(w * h * 4)
        c.windll.gdi32.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(bmpinfo), 0)
        from PIL import Image
        img2 = Image.frombuffer("RGB", (w, h), buf, "raw", "BGRX", 0, 1)
        img2.save(OUT)
        print("PrintWindow ok:", ok, "saved", OUT, img2.size)
    except Exception as e:
        img.save(OUT)
        print("fallback grab:", e)
proc.terminate()
try:
    proc.wait(5)
except Exception:
    proc.kill()
print("exit code:", proc.returncode)
