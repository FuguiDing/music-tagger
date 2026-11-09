# -*- coding: utf-8 -*-
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mtcore.sources import NetEaseSource, QQSource

for cls in (NetEaseSource, QQSource):
    s = cls()
    print("=" * 20, s.name)
    print("ping:", s.ping())
    try:
        res = s.search("周杰伦 晴天", 5)
        for c in res[:5]:
            print(f"  [{c.song_id}] {c.title} - {c.artists} | {c.album} | {c.duration:.0f}s | cover={bool(c.cover_url)}")
        if res:
            cov = s.fetch_cover(res[0])
            print("  cover bytes:", len(cov) if cov else None)
            lyr = s.fetch_lyrics(res[0])
            print("  lyric head:", (lyr or "")[:60].replace("\n", " / "))
    except Exception as e:
        print("  ERROR:", type(e).__name__, e)
