# -*- coding: utf-8 -*-
"""网易云音乐 / QQ音乐 搜索接口封装（仅用于个人本地音乐整理）。"""

import html
import json
import random
import re
import threading
import time
from typing import List, Optional

import requests

from .models import Candidate

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


class SourceError(Exception):
    pass


# 进程级限速：多个线程共享同一音源时按最小间隔串行发请求，避免被风控
_GLOBAL_LOCK = threading.Lock()
_LAST_CALL = {}


def _global_throttle(key: str, interval: float):
    with _GLOBAL_LOCK:
        wait = interval - (time.time() - _LAST_CALL.get(key, 0.0))
        if wait > 0:
            time.sleep(min(wait, 3.0))
        _LAST_CALL[key] = time.time()


class MusicSource:
    name = "base"
    short = "base"
    min_interval = 0.25

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": UA})
        self._lock = threading.Lock()
        self._last = 0.0

    # ---- 基础工具 ----
    def _throttle(self, interval=None):
        _global_throttle(self.short, interval or self.min_interval)

    def _get(self, url, params=None, headers=None, timeout=10):
        self._throttle()
        h = dict(self.session.headers)
        if headers:
            h.update(headers)
        r = self.session.get(url, params=params, headers=h, timeout=timeout)
        r.raise_for_status()
        return r

    def _post(self, url, data=None, headers=None, timeout=10):
        self._throttle()
        h = dict(self.session.headers)
        if headers:
            h.update(headers)
        r = self.session.post(url, data=data, headers=h, timeout=timeout)
        r.raise_for_status()
        return r

    @staticmethod
    def _json(text: str):
        text = text.strip()
        if not text:
            raise SourceError("返回内容为空")
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            m = re.search(r"^[\w$.]+\((.*)\)\s*;?\s*$", text, re.S)
            if m:
                return json.loads(m.group(1))
            raise SourceError("返回内容无法解析为 JSON")

    # ---- 子类实现 ----
    def search(self, keyword: str, limit: int = 12) -> List[Candidate]:
        raise NotImplementedError

    def enrich(self, cand: Candidate) -> Candidate:
        """补全发行日期、曲目号等搜索接口未返回的字段。"""
        return cand

    def fetch_cover(self, cand: Candidate) -> Optional[bytes]:
        return None

    def fetch_lyrics(self, cand: Candidate) -> Optional[str]:
        return None

    def ping(self) -> str:
        raise NotImplementedError


# --------------------------------------------------------------------------
# 网易云音乐
# --------------------------------------------------------------------------
class NetEaseSource(MusicSource):
    name = "网易云"
    short = "netease"
    min_interval = 0.20

    API_WEB = "https://music.163.com/api/search/get/web"
    API_CLOUD = "https://music.163.com/api/cloudsearch/pc"
    API_DETAIL = "https://music.163.com/api/song/detail"
    API_LYRIC = "https://music.163.com/api/song/lyric"
    H = {"Referer": "https://music.163.com/", "Origin": "https://music.163.com"}

    def __init__(self):
        super().__init__()
        self.session.headers.update(self.H)

    # 旧版搜索接口，返回 artists/album/duration 结构
    def _search_web(self, kw, limit):
        r = self._get(self.API_WEB, params={
            "s": kw, "type": 1, "offset": 0, "total": "true", "limit": limit,
        })
        data = self._json(r.text)
        songs = ((data.get("result") or {}).get("songs")) or []
        out = []
        for s in songs:
            artists = "/".join(a.get("name", "") for a in (s.get("artists") or []) if a.get("name"))
            album = s.get("album") or {}
            out.append(Candidate(
                source=self.name,
                song_id=str(s.get("id")),
                title=(s.get("name") or "").strip(),
                artists=artists,
                album=(album.get("name") or "").strip(),
                album_id=str(album.get("id") or ""),
                duration=(s.get("duration") or 0) / 1000.0,
                cover_url=self._pic_from_picid(album),
                extra={"kind": "web"},
            ))
        return out

    # 新版云搜索接口，返回 ar/al/dt 结构，自带封面
    def _search_cloud(self, kw, limit):
        r = self._post(self.API_CLOUD, data={
            "s": kw, "type": 1, "limit": limit, "offset": 0, "total": "true",
        }, headers=self.H)
        data = self._json(r.text)
        songs = ((data.get("result") or {}).get("songs")) or []
        out = []
        for s in songs:
            artists = "/".join(a.get("name", "") for a in (s.get("ar") or []) if a.get("name"))
            album = s.get("al") or {}
            out.append(Candidate(
                source=self.name,
                song_id=str(s.get("id")),
                title=(s.get("name") or "").strip(),
                artists=artists,
                album=(album.get("name") or "").strip(),
                album_id=str(album.get("id") or ""),
                duration=(s.get("dt") or 0) / 1000.0,
                cover_url=(album.get("picUrl") or ""),
                extra={"kind": "cloud"},
            ))
        return out

    @staticmethod
    def _pic_from_picid(album: dict) -> str:
        pid = album.get("picId") or album.get("pic")
        if not pid:
            return ""
        return f"https://p1.music.126.net/{pid}.jpg"

    def search(self, keyword, limit=12):
        errors = []
        for fn in (self._search_cloud, self._search_web):
            try:
                res = fn(keyword, limit)
                if res:
                    return res
            except Exception as e:  # noqa: BLE001
                errors.append(str(e))
        if errors and len(errors) == 2:
            raise SourceError(f"网易云搜索失败：{errors[0]}")
        return []

    def _detail(self, cand: Candidate) -> dict:
        r = self._get(self.API_DETAIL, params={"ids": "[%s]" % cand.song_id})
        data = self._json(r.text)
        songs = data.get("songs") or []
        return songs[0] if songs else {}

    def enrich(self, cand: Candidate) -> Candidate:
        """补全封面、发行日期、曲目号。"""
        try:
            s = self._detail(cand)
        except Exception:
            return cand
        if not s:
            return cand
        album = s.get("album") or {}
        if not cand.cover_url:
            cand.cover_url = album.get("picUrl") or ""
        pub = (album.get("publishTime") or 0)
        if pub:
            cand.release_date = time.strftime("%Y-%m-%d", time.localtime(pub / 1000))
        pos = s.get("position") or (s.get("no") or 0)
        if pos:
            cand.track_no = int(pos)
        if not cand.duration:
            cand.duration = (s.get("duration") or 0) / 1000.0
        if not cand.album:
            cand.album = (album.get("name") or "").strip()
        return cand

    def fetch_cover(self, cand: Candidate) -> Optional[bytes]:
        url = cand.cover_url
        if not url:
            self.enrich(cand)
            url = cand.cover_url
        if not url:
            return None
        url = url.split("?")[0] + "?param=600y600"
        try:
            r = self._get(url, headers={"Referer": "https://music.163.com/"})
            return r.content if len(r.content) > 1024 else None
        except Exception:
            return None

    def fetch_lyrics(self, cand: Candidate) -> Optional[str]:
        try:
            r = self._get(self.API_LYRIC, params={
                "id": cand.song_id, "lv": -1, "kv": -1, "tv": -1,
            })
            data = self._json(r.text)
            lrc = ((data.get("lrc") or {}).get("lyric") or "").strip()
            tlrc = ((data.get("tlyric") or {}).get("lyric") or "").strip()
            if lrc and tlrc:
                return lrc.rstrip() + "\n\n[译文]\n" + tlrc
            return lrc or None
        except Exception:
            return None

    def ping(self) -> str:
        try:
            res = self.search("周杰伦 晴天", 3)
            return f"正常（返回 {len(res)} 条）" if res else "连接成功但无结果"
        except Exception as e:  # noqa: BLE001
            return f"不可用：{e}"


# --------------------------------------------------------------------------
# QQ 音乐
# --------------------------------------------------------------------------
class _RateLimited(Exception):
    pass


class QQSource(MusicSource):
    name = "QQ音乐"
    short = "qq"
    min_interval = 0.32

    # musicu 接口被风控后，一段时间内直接走备用通道（进程内共享）
    _blocked_until = 0.0
    _blocked_reason = ""

    API_MUSICU = "https://u.y.qq.com/cgi-bin/musicu.fcg"
    API_SOSO = "https://c.y.qq.com/soso/fcgi-bin/search_for_qq_cp"
    API_LEGACY = "https://c.y.qq.com/soso/fcgi-bin/client_search_cp"
    API_LYRIC = "https://c.y.qq.com/lyric/fcgi-bin/fcg_query_lyric_new.fcg"
    H = {"Referer": "https://y.qq.com/"}

    def __init__(self):
        super().__init__()
        self.session.headers.update(self.H)

    # ---------------- 通道 1：musicu（信息最全）
    def _search_musicu(self, keyword, limit):
        payload = {
            "comm": {
                "ct": "11", "cv": "1003006", "v": "1003006", "uin": "0",
                "format": "json", "inCharset": "utf-8", "outCharset": "utf-8",
                "notice": 0, "platform": "yqq.json", "needNewCode": 0,
            },
            "req_1": {
                "module": "music.search.SearchCgiService",
                "method": "DoSearchForQQMusicDesktop",
                "param": {"num_per_page": limit, "page_num": 1,
                          "query": keyword, "search_type": 0},
            },
        }
        r = self._post(self.API_MUSICU, data=json.dumps(payload))
        data = self._json(r.text)
        req = data.get("req_1") or {}
        if req.get("code") in (2001, 1000, 2000):
            raise _RateLimited(f"code={req.get('code')}")
        body = ((req.get("data") or {}).get("body") or {})
        lst = ((body.get("song") or {}).get("list")) or []
        out = []
        for s in lst:
            singers = "/".join(x.get("name", "") for x in (s.get("singer") or []) if x.get("name"))
            album = s.get("album") or {}
            mid = album.get("mid") or ""
            out.append(Candidate(
                source=self.name,
                song_id=str(s.get("mid") or s.get("id") or ""),
                title=(s.get("title") or s.get("name") or "").strip(),
                artists=singers,
                album=(album.get("title") or album.get("name") or "").strip(),
                album_id=str(album.get("id") or ""),
                album_mid=mid,
                duration=float(s.get("interval") or 0),
                cover_url=self._cover_url(mid),
                release_date=(s.get("time_public") or "").strip(),
                extra={"kind": "musicu"},
            ))
        return out

    # ---------------- 通道 2：search_for_qq_cp（旧版但稳定）
    def _search_for_qq(self, keyword, limit):
        r = self._get(self.API_SOSO, params={
            "w": keyword, "format": "json", "n": str(limit), "p": "1",
            "cr": "1", "new_json": "1", "aggr": "1", "lossless": "0",
        }, headers={"Referer": "https://y.qq.com/portal/search.html"})
        data = self._json(r.text)
        lst = (((data.get("data") or {}).get("song") or {}).get("list")) or []
        return self._parse_old(lst)

    # ---------------- 通道 3：client_search_cp
    def _search_legacy(self, keyword, limit):
        r = self._get(self.API_LEGACY, params={
            "ct": "24", "qqmusic_ver": "1298", "new_json": "1",
            "remoteplace": "txt.yqq.song", "searchid": str(random.randint(10 ** 8, 10 ** 9)),
            "t": "0", "aggr": "1", "cr": "1", "catZhida": "1",
            "lossless": "0", "flag_qc": "0", "p": "1", "n": str(limit),
            "w": keyword, "format": "json",
        }, headers={"Referer": "https://y.qq.com/portal/search.html"})
        data = self._json(r.text)
        lst = (((data.get("data") or {}).get("song") or {}).get("list")) or []
        return self._parse_old(lst)

    def _parse_old(self, lst):
        out = []
        for s in lst:
            singers = "/".join(x.get("name", "") for x in (s.get("singer") or []) if x.get("name"))
            mid = s.get("albummid") or (s.get("album") or {}).get("mid") or ""
            pub = s.get("pubtime") or 0
            date = ""
            if isinstance(pub, (int, float)) and pub > 0:
                date = time.strftime("%Y-%m-%d", time.localtime(pub))
            out.append(Candidate(
                source=self.name,
                song_id=str(s.get("songmid") or s.get("mid") or s.get("songid") or ""),
                title=(s.get("songname") or s.get("title") or s.get("name") or "").strip(),
                artists=singers,
                album=(s.get("albumname") or (s.get("album") or {}).get("name") or "").strip(),
                album_id=str(s.get("albumid") or (s.get("album") or {}).get("id") or ""),
                album_mid=mid,
                duration=float(s.get("interval") or 0),
                cover_url=self._cover_url(mid),
                release_date=date,
                extra={"kind": "soso"},
            ))
        return out

    # ---------------- 对外接口
    def search(self, keyword, limit=12):
        if time.time() >= QQSource._blocked_until:
            for attempt in range(2):
                try:
                    res = self._search_musicu(keyword, limit)
                    if res:
                        return res
                  # 空结果也视为异常，尝试备用通道
                except _RateLimited as e:
                    QQSource._blocked_until = time.time() + 900
                    QQSource._blocked_reason = str(e)
                    break
                except Exception:
                    break
                time.sleep(0.3)

        for fn in (self._search_for_qq, self._search_legacy):
            try:
                res = fn(keyword, limit)
                if res:
                    return res
            except Exception:
                continue
        return []

    @staticmethod
    def _cover_url(album_mid: str, size: str = "500x500") -> str:
        if not album_mid:
            return ""
        return f"https://y.gtimg.cn/music/photo_new/T002R{size}M000{album_mid}.jpg"

    def fetch_cover(self, cand: Candidate) -> Optional[bytes]:
        if not cand.album_mid:
            return None
        for size in ("500x500", "300x300"):
            url = self._cover_url(cand.album_mid, size)
            try:
                r = self._get(url, headers={"Referer": "https://y.qq.com/"})
                if len(r.content) > 1024 and not r.content.startswith(b"<?xml"):
                    return r.content
            except Exception:
                continue
        return None

    def fetch_lyrics(self, cand: Candidate) -> Optional[str]:
        try:
            r = self._get(self.API_LYRIC, params={
                "songmid": cand.song_id, "format": "json", "nobase64": "1", "g_tk": "5381",
            }, headers={"Referer": "https://y.qq.com/portal/player.html"})
            data = self._json(r.text)
            lyric = html.unescape((data.get("lyric") or "").strip())
            trans = html.unescape((data.get("trans") or "").strip())
            if lyric and trans:
                return lyric.rstrip() + "\n\n[译文]\n" + trans
            return lyric or None
        except Exception:
            return None

    def ping(self) -> str:
        try:
            res = self.search("周杰伦 晴天", 3)
            if not res:
                return "可用但未返回结果（可能触发风控，稍后自动恢复）"
            return f"正常（返回 {len(res)} 条）"
        except Exception as e:  # noqa: BLE001
            return f"不可用：{e}"


SOURCES = {"netease": NetEaseSource, "qq": QQSource}
