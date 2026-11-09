# -*- coding: utf-8 -*-
"""候选打分与筛选。"""

import re
from typing import List, Optional

from .models import Candidate, TrackFile
from .textutil import artist_similarity, normalize, similarity

# 版本标记：本地文件名没有这些词、而候选项带有时，说明不是同一版本
_LIVE_RE = re.compile(r"live|现场|演唱会|concert|unplugged|不插电", re.I)
_ALT_RE = re.compile(r"cover|翻唱|伴奏|instrumental|纯音乐|remix|dj|抖音|"
                     r"钢琴|piano|吉他|guitar|acoustic|demo|片段|铃声|karaoke", re.I)


def _version_penalty(q_title: str, c_title: str) -> float:
    q, c = q_title or "", c_title or ""
    if _LIVE_RE.search(c) and not _LIVE_RE.search(q):
        return 0.90
    if _ALT_RE.search(c) and not _ALT_RE.search(q):
        return 0.88
    return 1.0


def _duration_score(local: float, remote: float) -> Optional[float]:
    if not local or not remote:
        return None
    diff = abs(local - remote)
    if diff <= 1.5:
        return 1.0
    if diff <= 5:
        return 1.0 - (diff - 1.5) * 0.06      # 1.0 -> 0.79
    if diff <= 12:
        return 0.79 - (diff - 5) * 0.09       # 0.79 -> 0.16
    if diff <= 30:
        return 0.10
    return 0.0


def _score_one(title_q: str, artist_q: str, album_q: str,
               track: TrackFile, cand: Candidate) -> float:
    t_score = similarity(title_q, cand.title)
    dur = _duration_score(track.duration, cand.duration)

    if artist_q:
        a_score = artist_similarity(artist_q, cand.artists)
        w = (0.52, 0.28, 0.16, 0.04)   # title, artist, duration, album
    else:
        a_score = 0.0
        w = (0.76, 0.0, 0.24, 0.0)

    al_score = similarity(album_q, cand.album) if album_q else 0.0

    total = t_score * w[0] + a_score * w[1] + al_score * w[3]
    wsum = w[0] + w[1] + w[3]
    if dur is None:
        total = total / wsum
    else:
        total += dur * w[2]

    if artist_q and a_score < 0.45:
        total *= 0.62
    if t_score < 0.4:
        total *= 0.5
    # 本地是单人、候选是合唱/合作版，略微降权
    if artist_q and "/" not in artist_q and cand.artists.count("/") >= 1:
        total *= 0.94
    total *= _version_penalty(title_q, cand.title)
    return min(total, 1.0)


def score_candidate(track: TrackFile, cand: Candidate) -> float:
    title_q = track.q_title or track.tag_title
    artist_q = track.q_artist or track.tag_artist
    album_q = track.tag_album

    best = _score_one(title_q, artist_q, album_q, track, cand)

    # 文件名可能是"歌名 - 歌手"或"歌手 - 歌名"，无正规标签时两种顺序都试
    tagged = bool(track.tag_title and track.tag_artist)
    if not tagged and title_q and artist_q:
        swapped = _score_one(artist_q, title_q, album_q, track, cand)
        best = max(best, swapped)
    return round(best, 4)


def dedupe(cands: List[Candidate]) -> List[Candidate]:
    out, seen = [], set()
    for c in cands:
        if not c.song_id or not c.title:
            continue
        key = (normalize(c.title), normalize(c.artists))
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out


def rank(track: TrackFile, candidates: List[Candidate]) -> List[Candidate]:
    candidates = dedupe(candidates)
    for c in candidates:
        c.score = score_candidate(track, c)
    candidates.sort(key=lambda c: (-c.score, abs((c.duration or 0) - (track.duration or 0))))
    return candidates


def best_of(candidates: List[Candidate]) -> Optional[Candidate]:
    return candidates[0] if candidates else None
