# -*- coding: utf-8 -*-
"""跨平台离线自测：扫描 → 写入 → 读回 → 撤销（不联网、不依赖声纹）。

用标准库 wave 模块合成音频，任意平台可跑：
    python tests/test_offline.py
"""

import os
import shutil
import struct
import sys
import tempfile
import wave

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from mtcore import media  # noqa: E402
from mtcore.models import Candidate, TrackFile  # noqa: E402


def make_wav(path: str, seconds: float = 3.0, freq: float = 440.0):
    rate = 44100
    n = int(rate * seconds)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = bytearray()
        for i in range(n):
            import math
            v = int(32767 * 0.6 * math.sin(2 * math.pi * freq * i / rate))
            frames += struct.pack("<h", v)
        w.writeframes(bytes(frames))


def main():
    tmp = tempfile.mkdtemp(prefix="mt_offline_")
    ok = True
    try:
        wav = os.path.join(tmp, "demo.wav")
        make_wav(wav)

        # ---- 扫描 ----
        tracks = media.scan_folder(tmp, recursive=False)
        assert len(tracks) == 1, f"扫描应有 1 个文件，得到 {len(tracks)}"
        t = tracks[0]
        print(f"[1] 扫描 OK: {t.filename} 时长 {t.duration:.1f}s")

        # ---- 写入（与界面层相同：先备份，再应用）----
        cand = Candidate(source="测试", song_id="1", title="测试歌名",
                         artists="测试歌手", album="测试专辑",
                         release_date="2026-11-10",
                         duration=t.duration)
        done, msg, info = media.apply_metadata(t, cand, overwrite=True)
        assert done, f"写入失败: {msg}"
        session = media.BackupSession()
        session.add(wav, info.get("before", {}), info.get("changed", []),
                    info.get("had_cover", True))
        bak = session.commit()
        assert bak and bak.exists(), "备份文件未生成"
        print(f"[2] 写入 OK: {msg}（备份 {bak.name}）")

        # ---- 读回 ----
        t2 = media.read_track(wav)
        assert t2.tag_title == "测试歌名", t2.tag_title
        assert t2.tag_artist == "测试歌手", t2.tag_artist
        assert t2.tag_album == "测试专辑", t2.tag_album
        print(f"[3] 读回 OK: {t2.tag_title} / {t2.tag_artist} / {t2.tag_album}")

        # ---- 撤销 ----
        n_restored, _, errors = media.restore_backup(bak)
        assert n_restored >= 1 and not errors, f"撤销失败: {errors}"
        t3 = media.read_track(wav)
        assert not t3.tag_title, f"撤销后 title 应为空，实际 {t3.tag_title!r}"
        print(f"[4] 撤销 OK: 标签已还原")

        # ---- 文件名解析（各平台一致）----
        from mtcore import textutil
        p = textutil.parse_filename("07.李荣浩 - 模特.flac")
        assert p["title"] == "模特" and p["artist"] == "李荣浩" and p["track"] == 7, p
        print("[5] 文件名解析 OK:", p["title"], "/", p["artist"])

        print("\n全部通过 ✔  平台:", sys.platform,
              " 数据目录:", media.APP_DIR)
    except AssertionError as e:
        ok = False
        print("\n断言失败 ✘:", e)
        raise
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
