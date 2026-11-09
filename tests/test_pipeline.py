# -*- coding: utf-8 -*-
"""端到端自测：生成样本音频 -> 解析 -> 搜索匹配 -> 写入标签 -> 撤销。"""

import os
import sys
import math
import numpy as np
import soundfile as sf

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mtcore import media, matcher
from mtcore.sources import NetEaseSource, QQSource

WORK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_samples")
os.makedirs(WORK, exist_ok=True)


def make_tone(path, seconds=8.0, sr=44100):
    n = int(seconds * sr)
    t = np.linspace(0, seconds, n, endpoint=False)
    x = 0.2 * np.sin(2 * math.pi * 440 * t)
    stereo = np.stack([x, x], axis=1).astype("float32")
    sf.write(path, stereo, sr)


cases = [
    ("晴天 - 周杰伦.wav", "wav"),
    ("陈奕迅 - 富士山下.flac", "flac"),
    ("03. Queen - Bohemian Rhapsody.flac", "flac"),
    ("赵雷 - 鼓楼.wav", "wav"),
]

print("== 生成样本 ==")
paths = []
for name, fmt in cases:
    p = os.path.join(WORK, name)
    make_tone(p, 8.0 if fmt == "wav" else 6.0)
    paths.append(p)
    print("  ", p, os.path.getsize(p), "bytes")

print("\n== 扫描 ==")
tracks = media.scan_folder(WORK, recursive=True)
for t in tracks:
    print(f"  {t.filename:38s} {t.ext:6s} {t.duration:5.1f}s  曲名={t.q_title!r} 歌手={t.q_artist!r} 封面={t.has_cover}")

ne, qq = NetEaseSource(), QQSource()

print("\n== 匹配 ==")
for t in tracks:
    from mtcore.textutil import build_queries
    qs = build_queries(t)
    print(f"  [{t.filename}] queries={qs}")
    cands = []
    for src in (ne, qq):
        for q in qs[:2]:
            try:
                cands += src.search(q, 8)
            except Exception as e:
                print("     源错误", src.name, e)
    ranked = matcher.rank(t, cands)
    for c in ranked[:3]:
        print(f"     {c.score:.3f} {c.source:5s} {c.title} - {c.artists} | {c.album} | {c.duration:.0f}s")

print("\n== 写入第一个样本 ==")
t = tracks[0]
qs = None
cands = []
for src in (ne, qq):
    for q in __import__("mtcore.textutil", fromlist=["x"]).build_queries(t)[:2]:
        try:
            cands += src.search(q, 8)
        except Exception:
            pass
ranked = matcher.rank(t, cands)
best = ranked[0]
print("  best:", best.source, best.title, best.artists, best.score)
cover = qq.fetch_cover(best) if best.source == "QQ音乐" else ne.fetch_cover(best)
lyric = qq.fetch_lyrics(best) if best.source == "QQ音乐" else ne.fetch_lyrics(best)
ok, msg, info = media.apply_metadata(t, best, cover=cover, lyrics=lyric)
print("  写入:", ok, msg, "| cover bytes:", len(cover) if cover else None)

print("\n== 读取验证 ==")
t2 = media.read_track(t.path)
print(f"  title={t2.tag_title!r} artist={t2.tag_artist!r} album={t2.tag_album!r} date={t2.tag_date!r} track={t2.tag_track!r} 封面={t2.has_cover}")

print("\n== 撤销测试 ==")
from mtcore.media import BackupSession
bs = BackupSession()
bs.add(t.path, info["before"], info["changed"])
f = bs.commit()
print("  备份文件:", f)
okn, failn, errs = media.restore_backup(f)
print("  还原:", okn, "成功", failn, "失败", errs[:2])
t3 = media.read_track(t.path)
print(f"  还原后 title={t3.tag_title!r} artist={t3.tag_artist!r} 封面={t3.has_cover}")
