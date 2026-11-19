"""Find the tempo of a track.

YouTube Music does not expose BPM, so tempos are looked up elsewhere, in order:

1. a local overrides CSV you maintain (always wins),
2. the on-disk cache of earlier lookups,
3. Deezer's public API (free, no key; ``bpm`` is 0 for many tracks),
4. GetSongBPM (free key from getsongbpm.com, set ``GETSONGBPM_API_KEY``),
5. optionally, beat tracking on Deezer's 30 s preview (``pip install .[analysis]``).
"""
from __future__ import annotations

import csv
import io
import json
import logging
import os
import re
import tempfile
import time
from difflib import SequenceMatcher
from pathlib import Path
from typing import Protocol

import requests

from .models import Track

log = logging.getLogger(__name__)

DEFAULT_CACHE = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "runnr-playlist" / "bpm_cache.json"
# Don't retry unknown tempos for this long.
NEGATIVE_TTL_S = 30 * 24 * 3600

_NOISE = re.compile(
    r"\s*[\(\[][^\)\]]*(official|video|audio|lyric|visualizer|remaster|hd|hq|explicit|clean|live)[^\)\]]*[\)\]]",
    re.I,
)
_FEAT = re.compile(r"\s*[\(\[]?\s*(feat\.?|ft\.?|featuring)\s.*$", re.I)


def clean_title(title: str) -> str:
    t = _NOISE.sub("", title)
    t = _FEAT.sub("", t)
    return t.strip(" -")


def _similar(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


class BpmProvider(Protocol):
    name: str

    def lookup(self, track: Track) -> float | None: ...


class OverridesProvider:
    """CSV with columns ``video_id,bpm`` or ``artist,title,bpm``."""

    name = "override"

    def __init__(self, path: str | Path | None):
        self.by_id: dict[str, float] = {}
        self.by_name: dict[tuple[str, str], float] = {}
        if path and Path(path).exists():
            for row in csv.DictReader(io.StringIO(Path(path).read_text())):
                bpm = float(row["bpm"])
                if row.get("video_id"):
                    self.by_id[row["video_id"].strip()] = bpm
                elif row.get("artist") and row.get("title"):
                    self.by_name[(row["artist"].strip().lower(), clean_title(row["title"]).lower())] = bpm

    def lookup(self, track: Track) -> float | None:
        if track.video_id in self.by_id:
            return self.by_id[track.video_id]
        title = clean_title(track.title).lower()
        for artist in track.artists:
            if (artist.lower(), title) in self.by_name:
                return self.by_name[(artist.lower(), title)]
        return None


class DeezerProvider:
    name = "deezer"
    BASE = "https://api.deezer.com"

    def __init__(self, session: requests.Session | None = None):
        self.http = session or requests.Session()
        self._last = 0.0
        # video_id -> 30 s preview URL, for PreviewAnalysisProvider.
        self.previews: dict[str, str] = {}

    def _get(self, url: str, **params) -> dict:
        # Deezer allows ~50 requests / 5 s; stay well under it.
        wait = 0.12 - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()
        r = self.http.get(url, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
        if isinstance(data, dict) and "error" in data:
            raise RuntimeError(f"Deezer error: {data['error']}")
        return data

    def _find(self, track: Track) -> dict | None:
        title = clean_title(track.title)
        artist = track.artists[0] if track.artists else ""
        queries = [f'artist:"{artist}" track:"{title}"', f"{artist} {title}"]
        for q in queries:
            results = self._get(f"{self.BASE}/search", q=q, limit=10).get("data", [])
            best, best_score = None, 0.0
            for r in results:
                score = _similar(r["title"], title) + _similar(r["artist"]["name"], artist)
                if track.duration_s and r.get("duration"):
                    score -= min(abs(r["duration"] - track.duration_s), 60) / 60
                if score > best_score:
                    best, best_score = r, score
            if best and best_score >= 1.3:
                return best
        return None

    def lookup(self, track: Track) -> float | None:
        hit = self._find(track)
        if not hit:
            return None
        detail = self._get(f"{self.BASE}/track/{hit['id']}")
        if detail.get("preview"):
            self.previews[track.video_id] = detail["preview"]
        bpm = detail.get("bpm") or 0
        return float(bpm) if bpm > 0 else None


class GetSongBpmProvider:
    name = "getsongbpm"
    BASE = "https://api.getsong.co"

    def __init__(self, api_key: str, session: requests.Session | None = None):
        self.key = api_key
        self.http = session or requests.Session()

    def lookup(self, track: Track) -> float | None:
        title = clean_title(track.title)
        artist = track.artists[0] if track.artists else ""
        r = self.http.get(
            f"{self.BASE}/search/",
            params={"api_key": self.key, "type": "both", "lookup": f"song:{title} artist:{artist}"},
            timeout=15,
        )
        r.raise_for_status()
        results = r.json().get("search") or []
        if isinstance(results, dict):  # {"error": "no result"}
            return None
        for res in results:
            name = (res.get("artist") or {}).get("name", "")
            if _similar(res.get("title", ""), title) > 0.75 and _similar(name, artist) > 0.6:
                tempo = res.get("tempo")
                if tempo and float(tempo) > 0:
                    return float(tempo)
        return None


class PreviewAnalysisProvider:
    """Estimate tempo with librosa from the Deezer preview found earlier."""

    name = "preview-analysis"

    def __init__(self, deezer: DeezerProvider):
        import librosa  # noqa: F401  (fail early if the extra is missing)

        self.deezer = deezer
        self.http = requests.Session()

    def lookup(self, track: Track) -> float | None:
        import librosa

        url = self.deezer.previews.get(track.video_id)
        if not url:
            return None
        r = self.http.get(url, timeout=30)
        r.raise_for_status()
        with tempfile.NamedTemporaryFile(suffix=".mp3") as f:
            f.write(r.content)
            f.flush()
            y, sr = librosa.load(f.name, sr=22050, mono=True)
        tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
        value = float(tempo[0] if hasattr(tempo, "__len__") else tempo)
        return round(value, 1) if value > 0 else None


class BpmResolver:
    def __init__(
        self,
        providers: list[BpmProvider],
        overrides: OverridesProvider | None = None,
        cache_path: str | Path | None = DEFAULT_CACHE,
    ):
        self.providers = providers
        self.overrides = overrides
        self.cache_path = Path(cache_path) if cache_path else None
        self.cache: dict[str, dict] = {}
        if self.cache_path and self.cache_path.exists():
            self.cache = json.loads(self.cache_path.read_text())
        self._dirty = 0

    def resolve(self, track: Track) -> float | None:
        if self.overrides and (bpm := self.overrides.lookup(track)):
            track.bpm, track.bpm_source = bpm, self.overrides.name
            return bpm
        hit = self.cache.get(track.video_id)
        if hit and (hit["bpm"] or time.time() - hit["at"] < NEGATIVE_TTL_S):
            track.bpm, track.bpm_source = hit["bpm"], hit.get("source")
            return track.bpm
        bpm, source = None, None
        for p in self.providers:
            try:
                bpm = p.lookup(track)
            except Exception as e:  # network hiccups shouldn't sink the run
                log.warning("%s lookup failed for %s: %s", p.name, track.label, e)
                continue
            if bpm:
                source = p.name
                break
        self.cache[track.video_id] = {"bpm": bpm, "source": source, "at": time.time(), "label": track.label}
        self._dirty += 1
        if self._dirty >= 20:
            self.save()
        track.bpm, track.bpm_source = bpm, source
        return bpm

    def save(self) -> None:
        if self.cache_path and self._dirty:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(json.dumps(self.cache, indent=1))
            self._dirty = 0


def build_resolver(
    overrides_csv: str | None = None,
    cache_path: str | Path | None = DEFAULT_CACHE,
    analyze_previews: bool = False,
) -> BpmResolver:
    deezer = DeezerProvider()
    providers: list[BpmProvider] = [deezer]
    if key := os.environ.get("GETSONGBPM_API_KEY"):
        providers.append(GetSongBpmProvider(key))
    if analyze_previews:
        providers.append(PreviewAnalysisProvider(deezer))
    return BpmResolver(providers, OverridesProvider(overrides_csv), cache_path)
