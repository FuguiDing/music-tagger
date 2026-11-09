# -*- coding: utf-8 -*-
"""音频扫描、标签读取/写入、备份与撤销。"""

import base64
import json
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import mutagen
from mutagen.apev2 import APEv2, APEValue
from mutagen.flac import FLAC, Picture
from mutagen.id3 import (APIC, ID3, TALB, TCON, TDRC, TIT2, TPE1, TPE2, TRCK,
                         USLT, ID3NoHeaderError)
from mutagen.mp4 import MP4, MP4Cover
from mutagen.oggopus import OggOpus
from mutagen.oggvorbis import OggVorbis
from mutagen.wave import WAVE

from .models import SUPPORTED_EXTS, Candidate, TrackFile
from .textutil import format_duration, parse_filename, safe_filename, strip_noise

FIELD_ORDER = ["title", "artist", "album", "albumartist", "date", "tracknumber", "genre"]

APP_DIR = Path(os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()) / "MusicTagger"
BACKUP_DIR = APP_DIR / "backups"


def _app_dir() -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    return BACKUP_DIR


# --------------------------------------------------------------------------
# 标签读写适配器
# --------------------------------------------------------------------------
class TagIO:
    """统一不同容器格式的标签读写。"""

    ID3_MAP = {
        "title": "TIT2", "artist": "TPE1", "album": "TALB",
        "albumartist": "TPE2", "date": "TDRC",
        "tracknumber": "TRCK", "genre": "TCON", "lyrics": "USLT",
    }
    MP4_MAP = {
        "title": "\xa9nam", "artist": "\xa9ART", "album": "\xa9alb",
        "albumartist": "aART", "date": "\xa9day",
        "tracknumber": "trkn", "genre": "\xa9gen", "lyrics": "\xa9lyr",
    }
    APE_MAP = {
        "title": "Title", "artist": "Artist", "album": "Album",
        "albumartist": "Album Artist", "date": "Year",
        "tracknumber": "Track", "genre": "Genre", "lyrics": "Lyrics",
    }

    def __init__(self, path: str):
        self.path = path
        self.audio = mutagen.File(path)
        if self.audio is None:
            raise ValueError("无法解析的音频文件（格式不支持或文件损坏）")
        self.kind = self._detect()

    def _detect(self) -> str:
        a = self.audio
        tags = getattr(a, "tags", None)
        if isinstance(tags, ID3):
            return "id3"
        if isinstance(tags, APEv2):
            return "ape"
        if isinstance(a, MP4):
            return "mp4"
        if isinstance(a, (FLAC, OggVorbis, OggOpus)):
            return "vorbis"
        if isinstance(a, WAVE):
            try:
                a.add_tags()
            except Exception:
                pass
            return "id3"
        if hasattr(a, "tags") and tags is not None and hasattr(tags, "keys"):
            return "vorbis"
        return "other"

    # ---- 读 ----
    def get(self, field: str) -> str:
        try:
            if self.kind == "id3":
                fid = self.ID3_MAP.get(field)
                if not fid or self.audio.tags is None:
                    return ""
                fr = self.audio.tags.get(fid)
                if fr is None:
                    return ""
                if fid == "USLT":
                    return str(getattr(fr, "text", "") or "")
                return str(fr)
            if self.kind == "mp4":
                key = self.MP4_MAP.get(field)
                if not key or not self.audio.tags or key not in self.audio.tags:
                    return ""
                val = self.audio.tags[key]
                if field == "tracknumber":
                    return str(val[0][0]) if val and val[0] else ""
                return str(val[0]) if isinstance(val, list) and val else str(val)
            if self.kind == "ape":
                key = self.APE_MAP.get(field)
                if not key or not self.audio.tags or key not in self.audio.tags:
                    return ""
                return str(self.audio.tags[key])
            # vorbis
            key = "albumartist" if field == "albumartist" else field
            if not self.audio.tags or key not in self.audio.tags:
                return ""
            val = self.audio.tags[key]
            return str(val[0]) if isinstance(val, list) and val else str(val)
        except Exception:
            return ""

    def has_cover(self) -> bool:
        try:
            if self.kind == "vorbis":
                if isinstance(self.audio, FLAC):
                    return bool(self.audio.pictures)
                key = "metadata_block_picture"
                return bool(self.audio.tags and key in self.audio.tags)
            if self.kind == "id3":
                if not self.audio.tags:
                    return False
                return bool(self.audio.tags.getall("APIC"))
            if self.kind == "mp4":
                return bool(self.audio.tags and "covr" in self.audio.tags)
            if self.kind == "ape":
                return bool(self.audio.tags and "Cover Art (Front)" in self.audio.tags)
        except Exception:
            pass
        return False

    # ---- 写 ----
    def set(self, field: str, value: str):
        value = (value or "").strip()
        if not value:
            return
        if self.kind == "id3":
            fid = self.ID3_MAP.get(field)
            if not fid:
                return
            if fid == "USLT":
                self.audio.tags.setall("USLT", [USLT(encoding=3, lang="eng", desc="", text=value)])
            elif fid == "TRCK":
                self.audio.tags.setall("TRCK", [TRCK(encoding=3, text=value)])
            elif fid == "TDRC":
                self.audio.tags.setall("TDRC", [TDRC(encoding=3, text=value)])
            else:
                from mutagen.id3 import Frames
                self.audio.tags.setall(fid, [Frames[fid](encoding=3, text=value)])
        elif self.kind == "mp4":
            key = self.MP4_MAP.get(field)
            if not key:
                return
            if field == "tracknumber":
                try:
                    self.audio.tags[key] = [(int(str(value).split("/")[0]), 0)]
                except ValueError:
                    return
            else:
                self.audio.tags[key] = [value]
        elif self.kind == "ape":
            key = self.APE_MAP.get(field)
            if not key:
                return
            self.audio.tags[key] = value
        else:
            key = field
            self.audio.tags[key] = value

    def delete(self, field: str):
        try:
            if self.kind == "id3":
                fid = self.ID3_MAP.get(field)
                if fid and self.audio.tags:
                    self.audio.tags.delall(fid)
            elif self.kind == "mp4":
                key = self.MP4_MAP.get(field)
                if key and self.audio.tags and key in self.audio.tags:
                    del self.audio.tags[key]
            elif self.kind == "ape":
                key = self.APE_MAP.get(field)
                if key and self.audio.tags and key in self.audio.tags:
                    del self.audio.tags[key]
            else:
                if self.audio.tags and field in self.audio.tags:
                    del self.audio.tags[field]
        except Exception:
            pass

    def set_cover(self, data: bytes, mime: str = "image/jpeg"):
        if not data:
            return False
        if self.kind == "vorbis":
            if isinstance(self.audio, FLAC):
                pic = Picture()
                pic.type = 3
                pic.mime = mime
                pic.desc = "Cover"
                pic.data = data
                self.audio.clear_pictures()
                self.audio.add_picture(pic)
            else:
                pic = Picture()
                pic.type = 3
                pic.mime = mime
                pic.desc = "Cover"
                pic.data = data
                self.audio.tags["metadata_block_picture"] = [
                    base64.b64encode(pic.write()).decode("ascii")
                ]
            return True
        if self.kind == "id3":
            self.audio.tags.delall("APIC")
            self.audio.tags.add(APIC(encoding=3, mime=mime, type=3, desc="Cover", data=data))
            return True
        if self.kind == "mp4":
            fmt = MP4Cover.FORMAT_PNG if mime == "image/png" else MP4Cover.FORMAT_JPEG
            self.audio.tags["covr"] = [MP4Cover(data, imageformat=fmt)]
            return True
        if self.kind == "ape":
            ext = ".png" if mime == "image/png" else ".jpg"
            try:
                self.audio.tags["Cover Art (Front)"] = APEValue(
                    ("cover" + ext).encode() + b"\x00" + data, binary=True)
            except TypeError:
                self.audio.tags["Cover Art (Front)"] = APEValue(
                    ("cover" + ext).encode() + b"\x00" + data)
            return True
        return False

    def save(self):
        self.audio.save()

    def remove_cover(self):
        try:
            if self.kind == "vorbis":
                if isinstance(self.audio, FLAC):
                    self.audio.clear_pictures()
                elif self.audio.tags and "metadata_block_picture" in self.audio.tags:
                    del self.audio.tags["metadata_block_picture"]
            elif self.kind == "id3":
                if self.audio.tags:
                    self.audio.tags.delall("APIC")
            elif self.kind == "mp4":
                if self.audio.tags and "covr" in self.audio.tags:
                    del self.audio.tags["covr"]
            elif self.kind == "ape":
                if self.audio.tags and "Cover Art (Front)" in self.audio.tags:
                    del self.audio.tags["Cover Art (Front)"]
        except Exception:
            pass

    def snapshot(self) -> Dict[str, str]:
        return {f: self.get(f) for f in FIELD_ORDER}


def sniff_mime(data: bytes) -> str:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    return "image/jpeg"


# --------------------------------------------------------------------------
# 扫描
# --------------------------------------------------------------------------
def read_track(path: str) -> TrackFile:
    p = Path(path)
    t = TrackFile(path=str(p), filename=p.name, ext=p.suffix.lower(), size=p.stat().st_size)
    try:
        io = TagIO(path)
    except Exception as e:  # noqa: BLE001
        t.error = str(e)
        guess = parse_filename(p.stem)
        t.q_title, t.q_artist = guess["title"], guess["artist"]
        return t
    t.tag_title = io.get("title")
    t.tag_artist = io.get("artist")
    t.tag_album = io.get("album")
    t.tag_albumartist = io.get("albumartist")
    t.tag_date = io.get("date")
    t.tag_track = io.get("tracknumber")
    t.tag_genre = io.get("genre")
    t.has_cover = io.has_cover()
    try:
        info = io.audio.info
        t.duration = float(getattr(info, "length", 0) or 0)
        t.bitrate = int(getattr(info, "bitrate", 0) or 0)
        t.sample_rate = int(getattr(info, "sample_rate", 0) or 0)
        t.bits = int(getattr(info, "bits_per_sample", 0) or 0)
    except Exception:
        pass
    guess = parse_filename(p.stem)
    t.q_title = t.tag_title or guess["title"]
    t.q_artist = t.tag_artist or guess["artist"]
    if not t.tag_track and guess["track"]:
        t.tag_track = ""
    return t


def scan_folder(folder: str, recursive: bool = True,
                on_progress=None, should_stop=None) -> List[TrackFile]:
    root = Path(folder)
    files: List[Path] = []
    if recursive:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            for fn in filenames:
                if Path(fn).suffix.lower() in SUPPORTED_EXTS:
                    files.append(Path(dirpath) / fn)
    else:
        for p in sorted(root.iterdir()):
            if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS:
                files.append(p)
    files.sort(key=lambda p: (str(p.parent).lower(), p.name.lower()))

    tracks = []
    for i, f in enumerate(files, 1):
        if should_stop and should_stop():
            break
        tracks.append(read_track(str(f)))
        if on_progress:
            on_progress(i, len(files), f.name)
    return tracks


# --------------------------------------------------------------------------
# 写入
# --------------------------------------------------------------------------
def apply_metadata(track: TrackFile, cand: Candidate,
                   cover: Optional[bytes] = None,
                   lyrics: Optional[str] = None,
                   overwrite: bool = True) -> Tuple[bool, str, dict]:
    try:
        io = TagIO(track.path)
    except Exception as e:  # noqa: BLE001
        return False, f"打开失败：{e}", {}

    before = io.snapshot()
    before_cover = io.has_cover()

    track_no = ""
    if cand.track_no:
        track_no = str(cand.track_no)
    elif track.tag_track:
        track_no = track.tag_track
    elif track.q_title:
        guess = parse_filename(Path(track.path).stem)
        track_no = str(guess["track"]) if guess["track"] else ""

    artists = (cand.artists or "").strip()
    albumartist = artists.split("/")[0].strip() if artists else ""
    date = (cand.release_date or "").strip()
    if date and len(date) >= 10:
        date = date[:10]

    values = {
        "title": cand.title.strip(),
        "artist": artists,
        "album": cand.album.strip(),
        "albumartist": albumartist,
        "date": date,
        "tracknumber": track_no,
        "genre": "",
    }
    changed = []
    for field, val in values.items():
        if not val:
            continue
        current = before.get(field, "")
        if current and not overwrite:
            continue
        if current == val:
            continue
        io.set(field, val)
        changed.append(field)

    if lyrics:
        if not before.get("lyrics") or overwrite:
            io.set("lyrics", lyrics)
            changed.append("lyrics")

    if cover:
        if not io.has_cover() or overwrite:
            if io.set_cover(cover, sniff_mime(cover)):
                changed.append("cover")

    try:
        io.save()
    except Exception as e:  # noqa: BLE001
        return False, f"写入失败：{e}", {"before": before, "changed": changed,
                                        "had_cover": before_cover}
    return True, "已写入 " + ("、".join(changed) if changed else "（无变化）"), {
        "before": before, "changed": changed, "had_cover": before_cover,
    }


def rename_file(track: TrackFile, cand: Candidate, template: str = "{artist} - {title}") -> Tuple[bool, str]:
    src = Path(track.path)
    try:
        name = template.format(
            artist=safe_filename(cand.artists.replace("/", "、") or "未知艺术家", 80),
            title=safe_filename(cand.title, 90),
            album=safe_filename(cand.album or "", 60),
            track=f"{cand.track_no:02d}" if cand.track_no else "",
        )
    except Exception:
        return False, "命名模板有误"
    name = safe_filename(name.strip(), 180)
    dst = src.with_name(name + src.suffix)
    if dst == src:
        return True, ""
    if dst.exists():
        for i in range(2, 30):
            cand_dst = src.with_name(f"{name} ({i}){src.suffix}")
            if not cand_dst.exists():
                dst = cand_dst
                break
        else:
            return False, "同名文件过多"
    try:
        src.rename(dst)
    except Exception as e:  # noqa: BLE001
        return False, f"重命名失败：{e}"
    track.path = str(dst)
    track.filename = dst.name
    return True, dst.name


# --------------------------------------------------------------------------
# 备份 / 撤销
# --------------------------------------------------------------------------
class BackupSession:
    def __init__(self):
        self.records: List[dict] = []

    def add(self, path: str, before: dict, changed: List[str], had_cover: bool = True):
        self.records.append({
            "path": path,
            "before": before,
            "changed": changed,
            "had_cover": bool(had_cover),
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        })

    def commit(self) -> Optional[Path]:
        if not self.records:
            return None
        _app_dir()
        f = BACKUP_DIR / time.strftime("undo_%Y%m%d_%H%M%S.json")
        data = {"created": time.strftime("%Y-%m-%d %H:%M:%S"), "records": self.records}
        f.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        self.records = []
        return f


def list_backups() -> List[Path]:
    if not BACKUP_DIR.exists():
        return []
    return sorted(BACKUP_DIR.glob("undo_*.json"), reverse=True)


def restore_backup(path: Path, on_progress=None) -> Tuple[int, int, List[str]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    records = data.get("records") or []
    ok = fail = 0
    errors: List[str] = []
    for i, rec in enumerate(records, 1):
        p = rec.get("path")
        if not p or not os.path.exists(p):
            fail += 1
            errors.append(f"文件不存在：{p}")
            continue
        try:
            io = TagIO(p)
            before = rec.get("before") or {}
            for field in FIELD_ORDER:
                val = (before.get(field) or "").strip()
                if val:
                    io.set(field, val)
                elif field in (rec.get("changed") or []):
                    io.delete(field)
            if (not rec.get("had_cover", True)) and "cover" in (rec.get("changed") or []):
                io.remove_cover()
            io.save()
            ok += 1
        except Exception as e:  # noqa: BLE001
            fail += 1
            errors.append(f"{os.path.basename(p)}：{e}")
        if on_progress:
            on_progress(i, len(records))
    return ok, fail, errors


def open_in_explorer(path: str):
    try:
        import subprocess
        if os.path.isdir(path):
            subprocess.Popen(["explorer", os.path.abspath(path)])
        else:
            subprocess.Popen(["explorer", "/select,", os.path.abspath(path)])
    except Exception:
        pass
