# -*- coding: utf-8 -*-
import os
import sys
import time
import ctypes
import ctypes.wintypes as wt

ctypes.windll.shcore.SetProcessDpiAwareness(2)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mtcore.app import App
from PIL import ImageGrab

WORK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_samples")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "shot.png")

app = App()
app.var_folder.set(WORK)
app.var_auto.set(False)
app.update()
app.start_scan()
while app.busy or not app.rows:
    app.update()
    time.sleep(0.05)

app.start_match()
t0 = time.time()
while app.busy and time.time() - t0 < 120:
    app.update()
    time.sleep(0.05)
for _ in range(10):
    app.update()
    time.sleep(0.05)

app.attributes("-topmost", True)
app.update()
time.sleep(0.5)
app.update()

h = ctypes.windll.user32.FindWindowW(None, app.title())
rc = wt.RECT()
ctypes.windll.user32.GetWindowRect(h, ctypes.byref(rc))
img = ImageGrab.grab(bbox=(rc.left, rc.top, rc.right, rc.bottom))
img.save(OUT)
print("saved", OUT, img.size, "rect", rc.left, rc.top, rc.right, rc.bottom)
app.destroy()
