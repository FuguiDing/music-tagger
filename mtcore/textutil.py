# -*- coding: utf-8 -*-
"""文本归一化、文件名解析与相似度计算。"""

import re
import unicodedata
from difflib import SequenceMatcher

_BRACKETS = [
    r"\([^()]*\)",
    r"\[[^\[\]]*\]",
    r"（[^（）]*）",
    r"【^【】*】",
    r"「[^「」]*」",
    r"『[^『』]*』",
]
_BRACKET_RE = re.compile("|".join(_BRACKETS))

NOISE_RE = re.compile(
    r"(?:\b(?:flac|ape|wav|wv|dsd|dsf|mqa|hires|hi-res|hq|sq|lossless|mp3|320k|"
    r"web-?dl|cd\s*rip|vinyl|remaster(?:ed)?|deluxe|explicit|clean)\b"
    r"|\b\d{2,3}\s*kbps\b|\b\d{1,3}\s*khz\b|\b(?:16|24|32)\s*-?\s*bit\b"
    r"|\b\d{2,3}\s*k\b|无损|高品质|高音质|正版|免费下载|抖音|完整版|超清|试听)",
    re.IGNORECASE,
)

_CJK = "\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"

_SEP = r"\s*(?:-|–|—|－|~|_)\s*"


def strip_brackets(text: str) -> str:
    prev = None
    cur = text
    # 反复剥离，处理嵌套括号
    for _ in range(3):
        prev = cur
        cur = _BRACKET_RE.sub(" ", cur)
        if cur == prev:
            break
    return cur


def strip_noise(text: str) -> str:
    if not text:
        return ""
    out = NOISE_RE.sub(" ", text)
    out = re.sub(r"[\[\]【】()（）]", " ", out)
    out = re.sub(r"_+", " ", out)
    out = re.sub(r"\s{2,}", " ", out)
    return out.strip(" -_.")


def normalize(text: str, keep_brackets: bool = False) -> str:
    """归一化：全角转半角、去括号内容、去标点、小写。"""
    if not text:
        return ""
    s = unicodedata.normalize("NFKC", text).lower()
    if not keep_brackets:
        s = strip_brackets(s)
    s = s.replace("&", " and ")
    s = re.sub(r"[\'’`\"“”·・]", "", s)
    s = re.sub(r"(?:\b(?:feat|ft|featuring|prod)\b\.?)", " ", s)
    s = re.sub(r"[^0-9a-z" + _CJK + r"]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def squash(text: str, keep_brackets: bool = False) -> str:
    return normalize(text, keep_brackets).replace(" ", "")


def similarity(a: str, b: str) -> float:
    """0~1 的标题相似度。"""
    if not a or not b:
        return 0.0
    best = 0.0
    for keep in (False, True):
        na, nb = normalize(a, keep), normalize(b, keep)
        if not na or not nb:
            continue
        if na == nb:
            best = max(best, 1.0)
            continue
        sa, sb = na.replace(" ", ""), nb.replace(" ", "")
        if sa == sb:
            best = max(best, 1.0)
            continue
        r = max(
            SequenceMatcher(None, na, nb).ratio(),
            SequenceMatcher(None, sa, sb).ratio(),
        )
        shorter, longer = (na, nb) if len(na) <= len(nb) else (nb, na)
        if len(shorter) >= 3 and shorter in longer:
            r = max(r, 0.90)
        best = max(best, r)
    return round(best, 4)


_SPLIT_ARTIST = re.compile(r"\s*(?:/|、|&|,|;|\bfeat\.?\b|\bft\.?\b|\bx\b|\+)\s*", re.I)


def artist_similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    whole = similarity(a, b)
    parts_a = [p for p in _SPLIT_ARTIST.split(a) if p.strip()]
    parts_b = [p for p in _SPLIT_ARTIST.split(b) if p.strip()]
    best = whole
    for pa in parts_a:
        for pb in parts_b:
            best = max(best, similarity(pa, pb))
    return round(best, 4)


_TRACK_PREFIX = re.compile(r"^\s*(?:cd\s*\d+\s*[-._ ]*)?(\d{1,3})\s*[\.\)、\-_ ]\s*(?=\S)", re.I)


def parse_filename(stem: str):
    """从文件名推断 (title, artist, album, track)。"""
    raw = stem
    track_no = 0
    m = _TRACK_PREFIX.match(raw)
    if m:
        track_no = int(m.group(1))
        raw = raw[m.end():]

    raw = strip_noise(raw)
    raw = raw.strip(" .-_")
    parts = [p.strip() for p in re.split(_SEP, raw) if p.strip()]

    title = artist = album = ""
    if len(parts) == 1:
        title = parts[0]
    elif len(parts) == 2:
        artist, title = parts[0], parts[1]
    elif len(parts) == 3:
        artist, album, title = parts[0], parts[1], parts[2]
    else:
        artist = parts[0]
        album = parts[1]
        title = parts[-1]
        if parts[-2].isdigit():
            track_no = track_no or int(parts[-2])

    if not title:
        title = strip_noise(stem)

    if artist and normalize(artist) in ("unknown", "unknown artist", "未知艺术家", "va", "various artists", "群星"):
        artist = "" if normalize(artist) != "群星" else "群星"
    return {
        "title": title.strip(),
        "artist": artist.strip(),
        "album": album.strip(),
        "track": track_no,
    }


def clean_field(text: str) -> str:
    """清理元数据里的杂讯（保留可读性）。"""
    if not text:
        return ""
    out = NOISE_RE.sub("", text)
    out = re.sub(r"\s{2,}", " ", out).strip(" -_/")
    return out or text.strip()


def build_queries(track) -> list:
    """构造搜索关键词列表（去重，最多 3 条）。"""
    import os

    qs = []
    title = clean_field(track.q_title or track.tag_title)
    artist = clean_field(track.q_artist or track.tag_artist)
    album = clean_field(track.tag_album)

    if title and artist:
        qs.append(f"{artist} {title}")
    if title:
        qs.append(f"{title} {artist}".strip())
    if not title and album:
        qs.append(album)

    stem = os.path.splitext(os.path.basename(track.path))[0]
    raw = strip_noise(stem)
    raw = _TRACK_PREFIX.sub("", raw).strip(" .-_")
    if raw and raw not in qs:
        qs.append(raw)

    out, seen = [], set()
    for q in qs:
        key = normalize(q)
        if key and key not in seen:
            seen.add(key)
            out.append(q)
    return out[:3]


def format_duration(seconds: float) -> str:
    if not seconds or seconds <= 0:
        return "--:--"
    seconds = int(round(seconds))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def safe_filename(name: str, max_len: int = 120) -> str:
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", name)
    name = re.sub(r"\s{2,}", " ", name).strip(" .")
    return name[:max_len] or "未命名"


# 无信息文件名：搜索这类词只会命中一堆同名占位曲目，必须交给声纹
_PLACEHOLDER_RE = re.compile(
    r"^(?:track|trk|cd|disc|disk|audio|song|music|file|part|vol|sa?mple)"
    r"[\s\-_.]*\d{0,3}$"
    r"|^(?:track|trk|cd|disc|disk|part|vol)\s*\d+\s*[-_.]\s*\d+$"
    r"|^\d{1,3}[\s\-_.]\d{1,3}$"
    r"|^\d{1,3}$"
    r"|^(?:unknown(?:\s*(?:artist|title|album|track))?"
    r"|unnamed|no\s*title|untitled\s*\d*|new\s*file(?:\s*\d+)?"
    r"|未知名|未命名|未知|未知艺术家|未知专辑|新建文件)$",
    re.IGNORECASE,
)

# 整段文件名都是这些词时，等同无信息
_FILLER_WORDS = {
    "音乐", "歌曲", "音频", "无损", "高音质", "高品质", "下载", "未知", "未知名",
    "unknown", "audio", "music", "song", "download", "lossless", "hires",
}


def is_placeholder(text: str) -> bool:
    """判断一段文本是否是占位/无意义内容（track01、01、未知艺术家…）。"""
    if not text:
        return True
    raw = unicodedata.normalize("NFKC", text).strip()
    if not raw:
        return True
    if _PLACEHOLDER_RE.match(raw):
        return True
    norm = normalize(text)
    if not norm:
        return True
    if norm.isdigit():
        return True
    return False


def query_is_weak(tag_title: str, tag_artist: str,
                  q_title: str, q_artist: str) -> bool:
    """判断本地线索是否弱到无法做文本搜索（此时应直接走声纹）。"""
    title = (tag_title or q_title or "").strip()
    artist = (tag_artist or q_artist or "").strip()
    if not title:
        return True
    if is_placeholder(title):
        return True
    # 标题只是「音乐」「无损」这类泛词，且没有歌手
    norm = normalize(title)
    if not norm:
        return True
    if not artist and norm in _FILLER_WORDS:
        return True
    # 标题极短（1~2 字符）且没有歌手，搜出来必然是噪声
    if len(norm) <= 2 and not artist:
        return True
    return False


def clean_acoustic_title(title: str, artists: str) -> "tuple[str, str]":
    """清理声纹返回的歌名/歌手：去掉 「罗马表(Roamer)」里的外文别名尾巴。

    Shazam 常返回「心要野 (Live)」「罗马表(Roamer)」这类带后缀的标题，
    直接拿去搜音源会降低命中率，故拆出主标题与可选的版本后缀。
    """
    t = (title or "").strip()
    a = (artists or "").strip()
    if not t:
        return t, a
    # 括号内是本曲名的外文直译时去掉，例如「罗马表(Roamer)」
    m = re.match(r"^(.*?)\s*[（(]\s*([A-Za-z0-9'&\-\. ]{2,40})\s*[)）]\s*$", t)
    if m and m.group(1).strip():
        main, alias = m.group(1).strip(), m.group(2).strip()
        # 主标题含中文、括号内为纯外文 → 视为别名
        if re.search(r"[\u4e00-\u9fff]", main) and not re.search(r"[\u4e00-\u9fff]", alias):
            t = main
    # 歌手同样可能带外文注音：「布衣(Bu Yi)」
    m2 = re.match(r"^(.*?)\s*[（(]\s*([A-Za-z0-9'&\-\. ]{2,40})\s*[)）]\s*$", a)
    if m2 and m2.group(1).strip():
        a = m2.group(1).strip()
    return t, a
