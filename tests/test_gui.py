# -*- coding: utf-8 -*-
"""界面冒烟测试：构建窗口 -> 扫描样例 -> 打印结果 -> 关闭。"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mtcore.app import App

WORK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_samples")

app = App()
app.var_folder.set(WORK)
app.update()

app.start_scan()
deadline = time.time() + 30
while time.time() < deadline:
    app.update()
    if app.rows and not app.busy:
        break
    time.sleep(0.05)

print("rows:", len(app.rows))
for r in app.rows:
    print("  ", r.track.filename, "|", r.status, "|", r.track.q_title, "-", r.track.q_artist,
          "|", r.track.duration_text)
print("status bar:", app.var_status.get())
print("log tail:")
print(app.log.get("1.0", "end").strip()[-400:])

app.update()
app.destroy()
print("GUI OK")
