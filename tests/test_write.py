# -*- coding: utf-8 -*-
"""写入 + 读回 + 撤销 全流程测试（作用在 _samples 上）。"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mtcore import media
from mtcore.app import App

WORK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_samples")

app = App()
app.var_folder.set(WORK)
app.var_auto.set(True)
app.var_cover.set(True)
app.var_lyrics.set(True)
app.var_threshold.set(0.79)
app.update()
app.start_scan()
while app.busy or not app.rows:
    app.update()
    time.sleep(0.05)

app.start_match()
deadline = time.time() + 180
while time.time() < deadline:
    app.update()
    if not app.busy:
        break
    time.sleep(0.05)

print("=== 写入后 ===")
for r in app.rows:
    t = media.read_track(r.track.path)
    print(f"{t.filename}")
    print(f"   标题={t.tag_title!r} 歌手={t.tag_artist!r} 专辑={t.tag_album!r}")
    print(f"   专辑艺术家={t.tag_albumartist!r} 日期={t.tag_date!r} 音轨={t.tag_track!r} 封面={t.has_cover} 状态={r.status}")
print(app.var_status.get())

backups = media.list_backups()
print("\n备份文件:", backups[0].name if backups else None)
if backups:
    ok, fail, errs = media.restore_backup(backups[0])
    print("撤销:", ok, "成功", fail, "失败", errs[:3])
    for r in app.rows:
        t = media.read_track(r.track.path)
        print(f"   还原 {t.filename}: 标题={t.tag_title!r} 歌手={t.tag_artist!r} 封面={t.has_cover}")

print(app.log.get("1.0", "end").strip()[-600:])
app.destroy()
