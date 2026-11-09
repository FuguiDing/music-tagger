# -*- coding: utf-8 -*-
"""匹配与写入的流水线封装（界面层只调用这里）。"""

from dataclasses import dataclass, field, replace
from typing import Dict, List, Optional, Tuple

from . import fingerprint as fpm
from . import media, matcher
from .models import Candidate, TrackFile
from .sources import MusicSource
from .textutil import build_queries, clean_acoustic_title, query_is_weak

# 声纹兜底的触发线：文本匹配低于阈值×该系数时才启用（避免每首都算指纹）
ACOUSTIC_TRIGGER_RATIO = 0.8


@dataclass
class Options:
    use_netease: bool = True
    use_qq: bool = True
    download_cover: bool = True
    download_lyrics: bool = False
    overwrite: bool = True
    rename: bool = False
    rename_template: str = "{artist} - {title}"
    threshold: float = 0.82
    auto_write: bool = True
    workers: int = 3
    limit: int = 10
    # ---- 声纹兜底
    use_acoustic: bool = True
    acoustic_engines: Tuple[str, ...] = ("acoustid", "shazam")
    acoustid_key: str = fpm.DEFAULT_API_KEY


@dataclass
class MatchResult:
    candidates: List[Candidate] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    acoustic: Optional[fpm.AcousticMatch] = None
    acoustic_note: str = ""

    @property
    def best(self) -> Optional[Candidate]:
        return self.candidates[0] if self.candidates else None

    @property
    def from_acoustic(self) -> bool:
        return self.acoustic is not None and bool(self.candidates)


def search_track(track: TrackFile, sources: List[MusicSource],
                 limit: int = 10, extra_query: Optional[str] = None) -> MatchResult:
    queries = ([extra_query] if extra_query else []) + build_queries(track)
    cands: List[Candidate] = []
    errors: List[str] = []
    dedup_q = []
    for q in queries:
        if q and q not in dedup_q:
            dedup_q.append(q)

    for src in sources:
        got = 0
        for q in dedup_q[:2]:
            try:
                res = src.search(q, limit)
                cands.extend(res)
                got += len(res)
            except Exception as e:  # noqa: BLE001
                errors.append(f"{src.name}: {e}")
            if got >= limit * 2:
                break

    ranked = matcher.rank(track, cands)
    # 对最优候选补全发行日期/曲目号（多一次请求，便于人工核对）
    if ranked and ranked[0].score >= 0.6:
        top = ranked[0]
        for src in sources:
            if src.name == top.source:
                try:
                    src.enrich(top)
                except Exception:
                    pass
                break
    return MatchResult(candidates=ranked, errors=errors)


# --------------------------------------------------------------- 声纹兜底
_acoustic_cache: Dict[tuple, fpm.AcousticID] = {}
_acoustic_lock = None


def acoustic_client(opts: Options) -> Optional[fpm.AcousticID]:
    """按配置复用声纹客户端（两路引擎内部均有节流与锁）。"""
    global _acoustic_lock
    import threading

    if _acoustic_lock is None:
        _acoustic_lock = threading.Lock()
    key = (tuple(opts.acoustic_engines), opts.acoustid_key)
    with _acoustic_lock:
        client = _acoustic_cache.get(key)
        if client is None:
            client = fpm.AcousticID(
                api_key=opts.acoustid_key,
                use_acoustid="acoustid" in opts.acoustic_engines,
                use_shazam="shazam" in opts.acoustic_engines,
            )
            _acoustic_cache[key] = client
        return client


def search_track_with_acoustic(track: TrackFile, sources: List[MusicSource],
                               opts: Options, extra_query: Optional[str] = None) -> MatchResult:
    """先走文本匹配；线索太弱或置信度不够时用声纹定位，再回音源验证。

    声纹只提供「歌名 + 歌手」，专辑/封面/歌词仍由网易云、QQ音乐补齐，
    并用文本相似度二次校验，避免 Shazam 偶尔的误识别被当成事实写入。
    """
    if not opts.use_acoustic:
        return search_track(track, sources, opts.limit, extra_query=extra_query)

    # track01.flac / 01.mp3 / 未知艺术家 这类文件名搜出来全是同名噪声（相似度
    # 还能到 85%），必须跳过文本阶段直接声纹。
    weak = query_is_weak(track.tag_title, track.tag_artist,
                         track.q_title, track.q_artist)
    if not weak or extra_query:
        res = search_track(track, sources, opts.limit, extra_query=extra_query)
        if res.best and res.best.score >= opts.threshold * ACOUSTIC_TRIGGER_RATIO:
            return res
    else:
        res = MatchResult()

    return _acoustic_flow(track, sources, opts, res)


def _acoustic_flow(track: TrackFile, sources: List[MusicSource],
                   opts: Options, res: MatchResult) -> MatchResult:
    """执行声纹识别，并用结果回查音源。"""
    client = acoustic_client(opts)
    if client is None or not client.available():
        res.errors.append("声纹通道不可用")
        return res

    matches, note = client.identify(track.path, track.duration, want=1)
    res.acoustic_note = note
    if not matches:
        if note:
            res.errors.append(note)
        return res

    ac = matches[0]
    res.acoustic = ac

    # 「罗马表(Roamer)」→「罗马表」：去掉外文别名，音源命中率更高
    title, artist = clean_acoustic_title(ac.title, ac.artists)
    probe = replace(track, q_title=title, q_artist=artist)
    res2 = search_track(probe, sources, opts.limit)
    res.errors.extend(res2.errors)

    verified = res2.best
    if verified is not None and verified.score >= 0.6:
        for c in res2.candidates:
            c.extra["acoustic"] = True
        res.candidates = res2.candidates
        return res

    # 音源没有这首歌（或对不上）——用声纹结果兜底，至少能写歌名歌手专辑
    cand = Candidate(
        source="声纹",
        song_id=ac.recording_id,
        title=title or ac.title,
        artists=artist or ac.artists,
        album=ac.album,
        release_date=ac.release_date,
        duration=track.duration,
        score=min(ac.score, 0.78),
    )
    cand.extra["acoustic_only"] = True
    res.candidates = [cand] + res2.candidates
    return res


class SourceRegistry:
    """按名称管理音源实例（线程安全使用同一 session 需注意，故按线程创建）。"""
    def __init__(self, opts: Options):
        self.opts = opts
        self._local = {}

    def sources(self) -> List[MusicSource]:
        import threading
        tid = threading.get_ident()
        pair = self._local.get(tid)
        if pair is None:
            from .sources import NetEaseSource, QQSource
            pair = {}
            if self.opts.use_netease:
                pair["网易云"] = NetEaseSource()
            if self.opts.use_qq:
                pair["QQ音乐"] = QQSource()
            self._local[tid] = pair
        return list(pair.values())

    def get(self, name: str) -> Optional[MusicSource]:
        for s in self.sources():
            if s.name == name:
                return s
        return None


def write_track(track: TrackFile, cand: Candidate, registry: SourceRegistry,
                opts: Options) -> Tuple[bool, str, dict]:
    src = registry.get(cand.source)
    if src is not None:
        try:
            cand = src.enrich(cand)
        except Exception:
            pass

    cover = None
    if opts.download_cover:
        try:
            cover = src.fetch_cover(cand) if src else None
        except Exception:
            cover = None

    lyrics = None
    if opts.download_lyrics:
        try:
            lyrics = src.fetch_lyrics(cand) if src else None
        except Exception:
            lyrics = None

    ok, msg, info = media.apply_metadata(
        track, cand, cover=cover, lyrics=lyrics, overwrite=opts.overwrite)
    if not ok:
        return False, msg, info

    if opts.rename:
        rok, rmsg = media.rename_file(track, cand, opts.rename_template)
        if not rok:
            msg = msg + f"；重命名失败：{rmsg}"
    return True, msg, info
