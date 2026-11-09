# -*- coding: utf-8 -*-
"""数据模型。"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

SUPPORTED_EXTS = {
    ".flac", ".wav", ".mp3", ".m4a", ".aac", ".mp4", ".ape", ".wv",
    ".aiff", ".aif", ".ogg", ".opus",
}

STATUS_PENDING = "待匹配"
STATUS_MATCHING = "匹配中"
STATUS_READY = "待确认"
STATUS_WRITTEN = "已写入"
STATUS_SKIPPED = "已跳过"
STATUS_FAILED = "失败"
STATUS_MANUAL = "人工确认"
STATUS_EXISTS = "已有标签"


@dataclass
class TrackFile:
    path: str
    filename: str = ""
    ext: str = ""
    size: int = 0
    duration: float = 0.0
    bitrate: int = 0
    sample_rate: int = 0
    bits: int = 0
    tag_title: str = ""
    tag_artist: str = ""
    tag_album: str = ""
    tag_albumartist: str = ""
    tag_date: str = ""
    tag_track: str = ""
    tag_genre: str = ""
    tag_lyrics: str = ""
    has_cover: bool = False
    q_title: str = ""
    q_artist: str = ""
    error: str = ""

    @property
    def display_artist(self) -> str:
        return self.tag_artist or self.q_artist

    @property
    def display_title(self) -> str:
        return self.tag_title or self.q_title

    @property
    def duration_text(self) -> str:
        from .textutil import format_duration
        return format_duration(self.duration)

    @property
    def tag_completeness(self) -> int:
        score = 0
        for v in (self.tag_title, self.tag_artist, self.tag_album, self.tag_date, self.tag_track):
            if v:
                score += 1
        if self.has_cover:
            score += 1
        return score


@dataclass
class Candidate:
    source: str
    song_id: str
    title: str = ""
    artists: str = ""
    album: str = ""
    album_id: str = ""
    album_mid: str = ""
    duration: float = 0.0
    cover_url: str = ""
    track_no: int = 0
    release_date: str = ""
    score: float = 0.0
    extra: Dict[str, Any] = field(default_factory=dict)

    @property
    def label(self) -> str:
        dur = ""
        if self.duration:
            m, s = divmod(int(round(self.duration)), 60)
            dur = f"{m}:{s:02d}"
        bits = [self.source, f"{self.title} - {self.artists}"]
        if self.album:
            bits.append(self.album)
        if dur:
            bits.append(dur)
        return " | ".join(bits)

    @property
    def key(self) -> str:
        return f"{self.source}:{self.song_id}"


@dataclass
class Row:
    track: TrackFile
    candidates: List[Candidate] = field(default_factory=list)
    best: Optional[Candidate] = None
    chosen: Optional[Candidate] = None
    status: str = STATUS_PENDING
    note: str = ""
    written: bool = False
    manual: bool = False
    acoustic: str = ""          # 声纹命中说明，如「Shazam 罗马表/布衣」

    @property
    def target(self) -> Optional[Candidate]:
        return self.chosen or self.best
