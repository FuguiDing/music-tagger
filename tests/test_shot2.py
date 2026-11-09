# -*- coding: utf-8 -*-
"""界面截图（含声纹设置对话框）。"""

import ctypes
import ctypes.wintypes as wt
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

from PIL import Image  # noqa: E402

from mtcore.app import App  # noqa: E402

WORK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_samples")


def grab(hwnd, out):
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
    img = Image.frombuffer("RGB", (w, h), buf, "raw", "BGRX", 0, 1)
    img.save(out)
    ctypes.windll.user32.ReleaseDC(hwnd, hdc)
    ctypes.windll.gdi32.DeleteObject(bmp)
    ctypes.windll.gdi32.DeleteDC(mem)
    return img.size


def find_hwnd(title):
    h = ctypes.windll.user32.FindWindowW(None, title)
    return h or None


app = App()
app.var_folder.set(WORK)
for _ in range(12):
    app.update()
    time.sleep(0.05)
app.start_scan()
for _ in range(160):
    app.update()
    time.sleep(0.05)

wid = int(app.winfo_id())
hwnd = ctypes.windll.user32.GetParent(wid) or wid
print("main hwnd:", hwnd)
print("size:", grab(hwnd, "tests/ui_main.png"))

# 打开声纹设置对话框
app.show_acoustic_settings()
for _ in range(20):
    app.update()
    time.sleep(0.05)
dlg = find_hwnd("声纹兜底设置")
print("dialog hwnd:", dlg)
if dlg:
    print("dialog size:", grab(dlg, "tests/ui_acoustic.png"))
app.destroy()
print("done")
