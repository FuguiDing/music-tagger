# -*- coding: utf-8 -*-
"""声纹兜底通道：双引擎指纹识别。

引擎 1 · AcoustID（Chromaprint）
    工具：内置 fpcalc.exe（约 4MB，自带解码器），回退系统 ffmpeg。
    特点：完全免费、无需账号，欧美曲库覆盖好，华语流行覆盖偏低。

引擎 2 · Shazam
    方式：soundfile 解码 → 单声道 16k PCM → Shazam 签名查询。
    特点：华语覆盖极好，但为非官方接口，需限速；对 Live/长前奏曲目，
          必须用「多个短片段 + 投票」，用整段反而容易误识别。

两个引擎只负责回答「这是什么歌」。拿到歌名/歌手后仍回到网易云 /
QQ音乐补全专辑、封面、歌词，并用文本相似度二次校验，防止误识别。
"""

import io
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import warnings
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import requests

from .textutil import normalize

# MusicBrainz Picard 使用的公开客户端密钥，可被用户替换为自己的
DEFAULT_API_KEY = "v8pQ6oyB"
API_URL = "https://api.acoustid.org/v2/lookup"

FP_LENGTH = 120          # Chromaprint 参与时长（秒）
FP_TIMEOUT = 40
SHAZAM_SEGMENT = 12      # 单段时长（秒），实测 12s 比 30s 准得多
SHAZAM_OFFSETS = (0.0, 0.36, 0.68)   # 采样位置（相对总时长）
SHAZAM_TIMEOUT = 20      # 单次请求超时（秒）


@dataclass
class AcousticMatch:
    """一条声纹识别结果。"""

    title: str = ""
    artists: str = ""
    album: str = ""
    release_date: str = ""
    score: float = 0.0
    engine: str = ""
    votes: int = 0
    recording_id: str = ""
    duration: float = 0.0
    year: str = ""

    @property
    def query(self) -> str:
        """用于回查音源的关键词。"""
        return " ".join(x for x in (self.title, self.artists) if x).strip()

    @property
    def label(self) -> str:
        bits = [f"{self.title} - {self.artists}"]
        if self.album:
            bits.append(self.album)
        return " | ".join(bits)

    @property
    def key(self) -> Tuple[str, str]:
        return normalize(self.title), normalize(self.artists)


# --------------------------------------------------------------- 工具定位
_fpcalc_cache: Optional[str] = None


def _base_dir() -> str:
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _fpcalc_candidates() -> List[str]:
    names = ["fpcalc.exe"] if os.name == "nt" else ["fpcalc"]
    out = []
    if os.environ.get("FPCALC"):
        out.append(os.environ["FPCALC"])
    dirs = [
        _base_dir(),
        os.path.join(_base_dir(), "tools"),
        os.path.dirname(os.path.abspath(__file__)),
    ]
    if sys.platform == "darwin":
        # GUI 启动的 .app 不继承 shell 的 PATH，显式补上 Homebrew 路径
        dirs += ["/opt/homebrew/bin", "/usr/local/bin"]
    if getattr(sys, "frozen", False):
        dirs.append(os.path.dirname(sys.executable))
    for d in dirs:
        if d:
            out.extend(os.path.join(d, n) for n in names)
    which = shutil.which("fpcalc")
    if which:
        out.append(which)
    return out


def find_fpcalc() -> Optional[str]:
    global _fpcalc_cache
    if _fpcalc_cache and os.path.isfile(_fpcalc_cache):
        return _fpcalc_cache
    for p in _fpcalc_candidates():
        if p and os.path.isfile(p):
            _fpcalc_cache = p
            return p
    return None


def find_ffmpeg() -> Optional[str]:
    return shutil.which("ffmpeg")


def _has_soundfile() -> bool:
    try:
        import soundfile  # noqa: F401
        import numpy  # noqa: F401
        return True
    except Exception:
        return False


def _has_shazam() -> bool:
    try:
        import shazamio  # noqa: F401
        return True
    except Exception:
        return False


def engine_status() -> Dict[str, str]:
    """各引擎可用性，用于界面展示。"""
    st = {}
    fp = find_fpcalc()
    if fp:
        st["acoustid"] = "可用（fpcalc）"
    elif find_ffmpeg():
        st["acoustid"] = "可用（ffmpeg）"
    else:
        st["acoustid"] = "缺少 fpcalc/ffmpeg"

    if not _has_shazam():
        st["shazam"] = "未安装 shazamio"
    elif not _has_soundfile():
        st["shazam"] = "缺少 soundfile/numpy"
    else:
        st["shazam"] = "可用"
    return st


# --------------------------------------------------------------- 子进程
def _run(cmd: List[str], timeout: int = FP_TIMEOUT) -> subprocess.CompletedProcess:
    kwargs = {"stdout": subprocess.PIPE, "stderr": subprocess.PIPE, "timeout": timeout}
    if os.name == "nt":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    return subprocess.run(cmd, **kwargs)


def _parse_fpcalc_json(raw: str) -> Optional[Tuple[float, str]]:
    raw = (raw or "").strip()
    if not raw:
        return None
    start = raw.find("{")
    if start < 0:
        return None
    try:
        data = json.loads(raw[start:])
    except Exception:
        return None
    fp = (data.get("fingerprint") or "").strip()
    if not fp:
        return None
    try:
        dur = float(data.get("duration") or 0.0)
    except (TypeError, ValueError):
        dur = 0.0
    return dur, fp


def chromaprint(path: str, length: int = FP_LENGTH) -> Optional[Tuple[float, str]]:
    """提取 (时长, Chromaprint 指纹)。"""
    fpcalc = find_fpcalc()
    if fpcalc:
        try:
            proc = _run([fpcalc, "-json", "-length", str(int(length)), path])
            parsed = _parse_fpcalc_json(proc.stdout.decode("utf-8", "replace"))
            if parsed:
                return parsed
        except Exception:
            pass
    ffmpeg = find_ffmpeg()
    if ffmpeg:
        try:
            proc = _run([ffmpeg, "-hide_banner", "-loglevel", "error", "-t", str(int(length)),
                         "-i", path, "-f", "chromaprint", "-fp_format", "base64", "-"])
            fp = proc.stdout.decode("utf-8", "replace").strip()
            if fp:
                return _ffmpeg_duration(ffmpeg, path) or float(length), fp
        except Exception:
            pass
    return None


def _ffmpeg_duration(ffmpeg: str, path: str) -> float:
    try:
        proc = _run([ffmpeg, "-hide_banner", "-i", path, "-f", "null", "-"], timeout=25)
        for line in proc.stderr.decode("utf-8", "replace").splitlines():
            if "Duration:" in line:
                seg = line.split("Duration:")[1].split(",")[0].strip()
                h, m, s = seg.split(":")
                return int(h) * 3600 + int(m) * 60 + float(s)
    except Exception:
        pass
    return 0.0


# --------------------------------------------------------------- 发动机
class AcoustIDEngine:
    """Chromaprint + AcoustID。"""

    name = "AcoustID"
    short = "acoustid"
    min_interval = 0.4

    def __init__(self, api_key: str = DEFAULT_API_KEY):
        self.api_key = (api_key or DEFAULT_API_KEY).strip()
        self.session = requests.Session()
        self._lock = threading.Lock()
        self._last = 0.0

    def available(self) -> bool:
        return bool(find_fpcalc() or find_ffmpeg())

    def _throttle(self):
        with self._lock:
            wait = self.min_interval - (time.time() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.time()

    def identify(self, path: str, duration: float = 0.0) -> List[AcousticMatch]:
        fp = chromaprint(path)
        if not fp:
            return []
        dur, fingerprint = fp
        self._throttle()
        payload = {
            "client": self.api_key,
            "meta": "recordings releasegroups",
            "duration": str(int(round(dur or duration or 0))),
            "fingerprint": fingerprint,
        }
        last = None
        for attempt in range(2):
            try:
                r = self.session.post(API_URL, data=payload, timeout=25,
                                      headers={"User-Agent": "MusicTagger/1.2"})
                data = r.json()
                if data.get("status") != "ok":
                    msg = (data.get("error") or {}).get("message") or ""
                    if "invalid API key" in msg:
                        raise RuntimeError("AcoustID 密钥无效")
                    raise RuntimeError(msg or "AcoustID 返回异常")
                return self._parse(data)
            except RuntimeError:
                raise
            except Exception as e:  # noqa: BLE001
                last = e
                time.sleep(0.8)
        raise RuntimeError(f"AcoustID 查询失败：{last}")

    @staticmethod
    def _parse(data: dict) -> List[AcousticMatch]:
        out: List[AcousticMatch] = []
        for res in data.get("results") or []:
            try:
                score = float(res.get("score") or 0.0)
            except (TypeError, ValueError):
                score = 0.0
            for rec in res.get("recordings") or []:
                title = (rec.get("title") or "").strip()
                if not title:
                    continue
                artists = " / ".join(
                    (a.get("name") or "").strip()
                    for a in (rec.get("artists") or [])
                    if (a.get("name") or "").strip()
                )
                album, date = "", ""
                for g in rec.get("releasegroups") or []:
                    album = (g.get("title") or "").strip()
                    date = (g.get("first-release-date") or "").strip()
                    if album:
                        break
                out.append(AcousticMatch(
                    title=title, artists=artists, album=album, release_date=date,
                    score=score, engine="AcoustID", votes=1,
                    recording_id=str(rec.get("id") or ""),
                    duration=float(rec.get("duration") or 0.0),
                ))
        out.sort(key=lambda m: -m.score)
        return out[:5]


class _AsyncRunner:
    """常驻后台事件循环，供 Shazam 复用长连接（每次 asyncio.run 重建
    session 会让单次请求从 1 秒涨到十几秒，并且更容易触发限流）。"""

    _instance: Optional["_AsyncRunner"] = None
    _init_lock = threading.Lock()

    @classmethod
    def get(cls) -> "_AsyncRunner":
        with cls._init_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def __init__(self):
        import asyncio

        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run, name="shazam-loop", daemon=True)
        self.thread.start()

    def _run(self):
        import asyncio

        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def submit(self, coro, timeout: float):
        import asyncio

        fut = asyncio.run_coroutine_threadsafe(coro, self.loop)
        return fut.result(timeout)


class ShazamEngine:
    """soundfile 解码 + Shazam 多段投票。"""

    name = "Shazam"
    short = "shazam"
    min_interval = 1.2
    _cooldown_until = 0.0   # 连续超时后进入冷却，避免拖慢整批任务

    def __init__(self):
        self._lock = threading.Lock()
        self._last = 0.0
        self._sh = None

    def available(self) -> bool:
        if time.time() < ShazamEngine._cooldown_until:
            return False
        return _has_shazam() and _has_soundfile()

    def _throttle(self):
        with self._lock:
            wait = self.min_interval - (time.time() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.time()

    # -- 解码：绕开严格解码器，任何能播放的文件都能吃下
    @staticmethod
    def _segment_wav(path: str, start: float, seconds: int = SHAZAM_SEGMENT) -> Optional[bytes]:
        import numpy as np
        import soundfile as sf

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            try:
                with sf.SoundFile(path) as fh:
                    sr = fh.samplerate
                    if start > 0:
                        fh.seek(min(int(sr * start), max(fh.frames - sr, 0)))
                    data = fh.read(frames=int(sr * seconds), dtype="float32", always_2d=True)
            except Exception:
                return None
        if data is None or len(data) < 2048:
            return None
        mono = data.mean(axis=1) if data.ndim > 1 else data
        if sr != 16000 and len(mono):
            n = max(int(round(len(mono) * 16000 / sr)), 1)
            mono = np.interp(np.linspace(0, len(mono) - 1, n),
                             np.arange(len(mono)), mono).astype("float32")
        pcm = (np.clip(mono, -1.0, 1.0) * 32767).astype("<i2")
        buf = io.BytesIO()
        sf.write(buf, pcm, 16000, format="WAV", subtype="PCM_16")
        return buf.getvalue()

    @staticmethod
    def _parse_track(track: dict) -> Optional[AcousticMatch]:
        title = (track.get("title") or "").strip()
        if not title:
            return None
        meta: Dict[str, str] = {}
        for sec in track.get("sections") or []:
            for item in sec.get("metadata") or []:
                k = (item.get("title") or "").strip()
                if k:
                    meta.setdefault(k, (item.get("text") or "").strip())
        return AcousticMatch(
            title=title,
            artists=(track.get("subtitle") or "").strip(),
            album=meta.get("Album", ""),
            release_date=meta.get("Released", ""),
            year=meta.get("Released", ""),
            engine="Shazam",
            votes=1,
            recording_id=str(track.get("key") or ""),
        )

    def _recognize_one(self, wav: bytes):
        import asyncio

        from shazamio import Shazam

        async def go():
            # 每次新建会话：Shazam 对复用的 keep-alive 连接会返回
            # ServerDisconnectedError，新建反而更稳（约 1~2 秒）。
            sh = Shazam()
            try:
                return await asyncio.wait_for(sh.recognize(wav), timeout=SHAZAM_TIMEOUT)
            finally:
                try:
                    await sh.close()
                except Exception:
                    pass

        return _AsyncRunner.get().submit(go(), timeout=SHAZAM_TIMEOUT + 8)

    def identify(self, path: str, duration: float = 0.0) -> List[AcousticMatch]:
        total = duration or 0.0
        if not total:
            try:
                import soundfile as sf
                with sf.SoundFile(path) as fh:
                    total = fh.frames / float(fh.samplerate or 1)
            except Exception:
                total = 0.0
        offsets = []
        for ratio in SHAZAM_OFFSETS:
            pos = 0.0 if total <= 0 else max(total * ratio - SHAZAM_SEGMENT / 2, 0.0)
            if total > 0 and pos + SHAZAM_SEGMENT > total:
                pos = max(total - SHAZAM_SEGMENT, 0.0)
            offsets.append(round(pos, 1))
        offsets = list(dict.fromkeys(offsets))

        hits: Dict[Tuple[str, str], AcousticMatch] = {}
        counter: Dict[Tuple[str, str], int] = {}
        errors: List[str] = []
        timeouts = 0
        for pos in offsets:
            wav = self._segment_wav(path, pos)
            if not wav:
                continue
            self._throttle()
            try:
                res = self._recognize_one(wav)
            except Exception as e:  # noqa: BLE001
                msg = f"{type(e).__name__}: {e}"
                errors.append(msg)
                if "Timeout" in msg:
                    timeouts += 1
                    # 连续两段超时——大概率被限流，直接放弃并冷却
                    if timeouts >= 2:
                        ShazamEngine._cooldown_until = time.time() + 300
                        raise RuntimeError("Shazam 请求超时，已暂停 5 分钟")
                continue
            track = (res or {}).get("track") or {}
            match = self._parse_track(track) if track else None
            if not match:
                continue
            k = match.key
            counter[k] = counter.get(k, 0) + 1
            if k not in hits:
                hits[k] = match
            # 已获两票，无需继续采样
            if counter[k] >= 2:
                break

        out = list(hits.values())
        for m in out:
            n = counter.get(m.key, 1)
            m.votes = n
            # 多段一致 → 高置信；单段命中 → 存疑
            m.score = 0.93 if n >= 2 else 0.62
        out.sort(key=lambda m: (-m.votes, -m.score))
        if not out and errors:
            raise RuntimeError(f"Shazam 查询失败：{errors[0]}")
        return out


# --------------------------------------------------------------- 统一入口
class AcousticID:
    """声纹识别门面：按顺序尝试各引擎。"""

    def __init__(self, api_key: str = DEFAULT_API_KEY,
                 use_acoustid: bool = True, use_shazam: bool = True):
        self.engines = []
        if use_acoustid:
            self.engines.append(AcoustIDEngine(api_key))
        if use_shazam:
            self.engines.append(ShazamEngine())

    def available(self) -> bool:
        return any(e.available() for e in self.engines)

    def identify(self, path: str, duration: float = 0.0,
                 want: int = 1) -> Tuple[List[AcousticMatch], str]:
        """返回 (候选列表, 说明)。候选按置信度排序，通常取第一个。"""
        if not self.engines:
            return [], "未启用声纹通道"
        notes, errors = [], []
        collected: List[AcousticMatch] = []
        for eng in self.engines:
            if not eng.available():
                errors.append(f"{eng.name} 不可用")
                continue
            try:
                got = eng.identify(path, duration)
            except Exception as e:  # noqa: BLE001
                errors.append(f"{eng.name}: {e}")
                continue
            if got:
                collected.extend(got)
                notes.append(f"{eng.name} 命中")
                # 高置信命中后不再调用后续引擎，省时省钱
                if got[0].score >= 0.9:
                    break

        if not collected:
            msg = "；".join(errors) if errors else "声纹库未收录"
            return [], msg

        # 同一首歌被两个引擎同时识别 → 置信度提升
        merged: Dict[Tuple[str, str], AcousticMatch] = {}
        for m in collected:
            k = m.key
            if k in merged:
                prev = merged[k]
                prev.votes += m.votes
                prev.score = min(0.99, max(prev.score, m.score) + 0.05)
                if not prev.album and m.album:
                    prev.album = m.album
                if not prev.release_date and m.release_date:
                    prev.release_date = m.release_date
                prev.engine = prev.engine + "+" + m.engine
            else:
                merged[k] = m
        out = sorted(merged.values(), key=lambda m: (-m.score, -m.votes))
        return out[:max(want, 5)], "；".join(dict.fromkeys(notes)) or "声纹命中"


def identify(path: str, client: Optional[AcousticID],
             duration: float = 0.0) -> Tuple[Optional[AcousticMatch], str]:
    """便捷函数：返回 (最佳结果, 说明)。"""
    if client is None:
        return None, "未启用声纹通道"
    matches, note = client.identify(path, duration, want=1)
    return (matches[0] if matches else None), note
