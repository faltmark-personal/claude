"""Find the tempo of a track.

Neither YouTube Music nor the YouTube Data API exposes BPM, so tempos come
from elsewhere, tried in this order:

1. your manual BPM overrides (edited in the web app; always win),
2. the on-disk cache of earlier lookups,
3. Deezer's public catalogue API (free, no key). Coverage is partial: many
   tracks report ``bpm: 0``, which counts as unknown,
4. GetSongBPM (free key from getsongbpm.com; set ``GETSONGBPM_API_KEY``),
5. optionally, beat tracking on Deezer's 30 s preview clip
   (``pip install '.[analysis]'`` and enable it in settings).

Published and estimated tempos are sometimes off by a factor of two (a
"half-time" 85 vs 170 confusion). Half/double-time matching in ``ZoneMap``
mostly absorbs this. Tracks whose tempo stays unknown are never placed by
BPM; they show up in the library view so you can type a BPM in.
"""
from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import threading
import time
from difflib import SequenceMatcher
from pathlib import Path
from typing import Protocol

import requests

from .models import Track

log = logging.getLogger(__name__)

NEGATIVE_TTL_S = 30 * 24 * 3600  # don't retry unknown tempos for a month

_NOISE = re.compile(
    r"\s*[\(\[][^\)\]]*(official|video|audio|lyric|visuali[sz]er|remaster|hd|hq|explicit|clean|live|mv)[^\)\]]*[\)\]]",
    re.I,
)
_FEAT = re.compile(r"\s*[\(\[]?\s*(feat\.?|ft\.?|featuring)\s.*$", re.I)


def clean_title(title: str) -> str:
    return _FEAT.sub("", _NOISE.sub("", title)).strip(" -")


def clean_artist(name: str) -> str:
    return re.sub(r"\s*-\s*Topic$", "", name).strip()


def similar(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


class BpmProvider(Protocol):
    name: str

    def lookup(self, track: Track) -> float | None: ...


class Deezer:
    """Small client for Deezer's public API: tempo lookups and artist discovery."""

    name = "deezer"
    BASE = "https://api.deezer.com"

    def __init__(self, session: requests.Session | None = None):
        self.http = session or requests.Session()
        self._last = 0.0
        self._lock = threading.Lock()
        self.previews: dict[str, str] = {}  # track key -> preview URL

    def get(self, path: str, **params) -> dict:
        with self._lock:  # Deezer allows ~50 requests / 5 s; stay well under
            wait = 0.12 - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
        r = self.http.get(f"{self.BASE}{path}", params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
        if isinstance(data, dict) and "error" in data:
            raise RuntimeError(f"Deezer error: {data['error']}")
        return data

    def find_track(self, title: str, artist: str, duration_s: int = 0) -> dict | None:
        title = clean_title(title)
        for q in (f'artist:"{artist}" track:"{title}"', f"{artist} {title}"):
            best, best_score = None, 0.0
            for r in self.get("/search", q=q, limit=10).get("data", []):
                score = similar(r["title"], title) + similar(r["artist"]["name"], artist)
                if duration_s and r.get("duration"):
                    score -= min(abs(r["duration"] - duration_s), 60) / 60
                if score > best_score:
                    best, best_score = r, score
            if best and best_score >= 1.3:
                return best
        return None

    def track(self, deezer_id: int) -> dict:
        return self.get(f"/track/{deezer_id}")

    def find_artist(self, name: str) -> dict | None:
        for a in self.get("/search/artist", q=name, limit=5).get("data", []):
            if similar(a["name"], name) > 0.85:
                return a
        return None

    def related_artists(self, artist_id: int, limit: int = 10) -> list[dict]:
        return self.get(f"/artist/{artist_id}/related", limit=limit).get("data", [])

    def top_tracks(self, artist_id: int, limit: int = 15) -> list[dict]:
        return self.get(f"/artist/{artist_id}/top", limit=limit).get("data", [])

    # BpmProvider
    def lookup(self, track: Track) -> float | None:
        if track.deezer_id:
            detail = self.track(track.deezer_id)
        else:
            hit = self.find_track(track.title, track.artists[0] if track.artists else "", track.duration_s)
            if not hit:
                return None
            detail = self.track(hit["id"])
        if detail.get("preview"):
            self.previews[track.key] = detail["preview"]
        bpm = detail.get("bpm") or 0
        return float(bpm) if bpm > 0 else None


class GetSongBpm:
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
        if not isinstance(results, list):  # {"error": "no result"}
            return None
        for res in results:
            name = (res.get("artist") or {}).get("name", "")
            if similar(res.get("title", ""), title) > 0.75 and similar(name, artist) > 0.6:
                tempo = res.get("tempo")
                if tempo and float(tempo) > 0:
                    return float(tempo)
        return None


class PreviewAnalysis:
    """Estimate tempo with librosa from the Deezer preview found by an earlier lookup."""

    name = "preview-analysis"

    def __init__(self, deezer: Deezer):
        import librosa  # noqa: F401  (fail early if the optional extra is missing)

        self.deezer = deezer
        self.http = requests.Session()

    def lookup(self, track: Track) -> float | None:
        import librosa

        url = self.deezer.previews.get(track.key)
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
    def __init__(self, providers: list[BpmProvider], overrides: dict[str, float] | None = None,
                 cache_path: str | Path | None = None):
        self.providers = providers
        self.overrides = overrides if overrides is not None else {}
        self.cache_path = Path(cache_path) if cache_path else None
        self.cache: dict[str, dict] = {}
        if self.cache_path and self.cache_path.exists():
            self.cache = json.loads(self.cache_path.read_text())
        self._dirty = 0
        self._lock = threading.Lock()

    def resolve(self, track: Track, refresh: bool = False) -> float | None:
        if track.key in self.overrides:
            track.bpm, track.bpm_source = float(self.overrides[track.key]), "manual"
            return track.bpm
        hit = self.cache.get(track.key)
        if hit and not refresh and (hit["bpm"] or time.time() - hit["at"] < NEGATIVE_TTL_S):
            track.bpm, track.bpm_source = hit["bpm"], hit.get("source")
            return track.bpm
        if track.bpm and track.bpm_source:  # e.g. already known from a Deezer recommendation
            bpm, source = track.bpm, track.bpm_source
        else:
            bpm, source = None, None
            for p in self.providers:
                try:
                    bpm = p.lookup(track)
                except Exception as e:  # a flaky provider shouldn't sink the run
                    log.warning("%s lookup failed for %s: %s", p.name, track.label, e)
                    continue
                if bpm:
                    source = p.name
                    break
        with self._lock:
            self.cache[track.key] = {"bpm": bpm, "source": source, "at": time.time(), "label": track.label}
            self._dirty += 1
        if self._dirty >= 25:
            self.save()
        track.bpm, track.bpm_source = bpm, source
        return bpm

    def save(self) -> None:
        with self._lock:
            if self.cache_path and self._dirty:
                self.cache_path.parent.mkdir(parents=True, exist_ok=True)
                tmp = self.cache_path.with_suffix(".tmp")
                tmp.write_text(json.dumps(self.cache))
                tmp.replace(self.cache_path)
                self._dirty = 0


def build_providers(deezer: Deezer, analyze_previews: bool = False) -> list[BpmProvider]:
    providers: list[BpmProvider] = [deezer]
    if key := os.environ.get("GETSONGBPM_API_KEY"):
        providers.append(GetSongBpm(key))
    if analyze_previews:
        try:
            providers.append(PreviewAnalysis(deezer))
        except ImportError:
            log.warning("Preview analysis needs `pip install '.[analysis]'`; skipping it")
    return providers
