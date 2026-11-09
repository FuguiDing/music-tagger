# -*- coding: utf-8 -*-
"""匹配流程测试（不自动写入）。"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mtcore.app import App

WORK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_samples")

app = App()
app.var_folder.set(WORK)
app.var_auto.set(False)
app.update()
app.start_scan()
while app.busy or not app.rows:
    app.update()
    time.sleep(0.05)

app.start_match()
deadline = time.time() + 120
while time.time() < deadline:
    app.update()
    if not app.busy and all(r.status != "匹配中" for r in app.rows) and app.rows:
        break
    time.sleep(0.05)

print("=== 匹配结果 ===")
for r in app.rows:
    print(f"{r.track.filename}  [{r.status}]")
    for c in r.candidates[:3]:
        print(f"    {c.score:.3f} {c.source:5s} {c.title} - {c.artists} | {c.album} | {c.duration:.0f}s | cover={'Y' if c.cover_url else 'N'} | date={c.release_date}")
print(app.var_status.get())
print("--- log ---")
print(app.log.get("1.0", "end").strip()[-800:])
app.destroy()
