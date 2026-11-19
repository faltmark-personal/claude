"""Recommend songs when your liked songs don't cover a zone's tempo range.

Order of preference:
1. other popular songs by artists you've liked ("liked-artist"),
2. popular songs by artists similar to those ("similar-artist"),
3. song radio seeded from your liked songs, if the source supports it ("radio").

Artist data comes from a *catalog* (Deezer's public API by default). Its
tracks usually carry a BPM, which lets us filter by tempo before spending
YouTube API quota on finding the songs on YouTube.
"""
from __future__ import annotations

import logging
from collections import Counter
from typing import Protocol

from .bpm import BpmResolver, clean_artist
from .models import Track
from .zones import ZoneMap

log = logging.getLogger(__name__)


class Catalog(Protocol):
    def find_artist(self, name: str) -> dict | None: ...
    def related_artists(self, artist_id: int, limit: int = 10) -> list[dict]: ...
    def top_tracks(self, artist_id: int, limit: int = 15) -> list[dict]: ...


def _catalog_track(d: dict, origin: str, reason: str) -> Track:
    return Track(title=d["title"], artists=[d["artist"]["name"]], duration_s=int(d.get("duration") or 0),
                 deezer_id=d.get("id"), origin=origin, reason=reason,
                 bpm=(float(d["bpm"]) if d.get("bpm") else None), bpm_source="deezer" if d.get("bpm") else None)


class Recommender:
    def __init__(self, catalog: Catalog, resolver: BpmResolver, zones: ZoneMap, source=None,
                 max_lookups: int = 150, max_artists: int = 12):
        self.catalog = catalog
        self.resolver = resolver
        self.zones = zones
        self.source = source
        self.max_lookups = max_lookups
        self.max_artists = max_artists

    def recommend(self, liked: list[Track], need_s: dict[int, int], exclude: set[str]) -> list[Track]:
        """Return tracks that fit the zones in ``need_s`` until each has ~1.5x the needed time."""
        want = {z: int(s * 1.5) + 240 for z, s in need_s.items() if s > 0}
        if not want:
            return []
        have = {z: 0 for z in want}
        found: list[Track] = []
        seen = set(exclude)
        seen_names = {(t.artist.lower(), t.title.lower()) for t in liked}
        lookups = 0

        def consider(t: Track) -> None:
            nonlocal lookups
            if t.key in seen or (t.artist.lower(), t.title.lower()) in seen_names:
                return
            if not 90 <= t.duration_s <= 10 * 60:
                return
            seen.add(t.key)
            seen_names.add((t.artist.lower(), t.title.lower()))
            if not t.bpm:
                if lookups >= self.max_lookups:
                    return
                lookups += 1
            self.resolver.resolve(t)
            zones_hit = [z for z in want if self.zones.effective_bpm(t.bpm, z)]
            if zones_hit:
                found.append(t)
                for z in zones_hit:
                    have[z] += t.duration_s

        def done() -> bool:
            return all(have[z] >= want[z] for z in want) or lookups >= self.max_lookups

        # Artists ranked by how many of your liked songs they have, favouring
        # those whose songs already sit in a needed zone.
        counts = Counter(clean_artist(t.artists[0]) for t in liked if t.artists)
        zone_bias = Counter(clean_artist(t.artists[0]) for t in liked if t.artists
                            and any(self.zones.effective_bpm(t.bpm, z) for z in want))
        artists = sorted(counts, key=lambda a: -(counts[a] + 2 * zone_bias[a]))[: self.max_artists]

        catalog_ids: dict[str, int] = {}
        for name in artists:
            if done():
                break
            try:
                a = self.catalog.find_artist(name)
                if not a:
                    continue
                catalog_ids[name] = a["id"]
                for d in self.catalog.top_tracks(a["id"]):
                    consider(_catalog_track(d, "liked-artist", f"More from {name} (you like {counts[name]})"))
            except Exception as e:
                log.warning("Catalog lookup for %s failed: %s", name, e)

        for name, aid in catalog_ids.items():
            if done():
                break
            try:
                for rel in self.catalog.related_artists(aid, limit=6):
                    if done():
                        break
                    for d in self.catalog.top_tracks(rel["id"], limit=10):
                        consider(_catalog_track(d, "similar-artist", f"Similar to {name}"))
            except Exception as e:
                log.warning("Related artists for %s failed: %s", name, e)

        if self.source is not None and not done():
            seeds = [t for t in liked if any(self.zones.effective_bpm(t.bpm, z) for z in want)][:8]
            for seed in seeds:
                if done():
                    break
                try:
                    for t in self.source.similar_tracks(seed):
                        consider(t)
                except Exception as e:
                    log.warning("Similar tracks for %s failed: %s", seed.label, e)
        self.resolver.save()
        return found
