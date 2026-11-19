"""Offline demo library and catalog with made-up artists and songs, so the app
can be tried (and tested) without connecting any account."""
from __future__ import annotations

import random

from ..models import Track

_ARTISTS = ["Neon Harbor", "The Paper Lanterns", "Velvet Circuit", "Juniper Static", "Kilo Echo",
            "Marigold Avenue", "Solar Drift", "The Quiet Engines", "Copper Tide", "Lumen Bay"]
_SIMILAR = {a: [f"{a.split()[-1]} Collective", f"Nova {a.split()[-1]}", f"{a.split()[0]} & Co"] for a in _ARTISTS}
_WORDS = ["Midnight", "Runner", "Signal", "Glow", "Horizon", "Pulse", "Gravity", "Static", "Ember", "Rush",
          "Paper", "Skyline", "Wildfire", "Breathe", "Atlas", "Echo", "Velocity", "Summit", "Lights", "Tide"]


def _song(rng: random.Random) -> str:
    return " ".join(rng.sample(_WORDS, rng.choice([1, 2, 2, 3])))


class DemoSource:
    name = "demo"
    official = True

    def __init__(self, seed: int = 7):
        rng = random.Random(seed)
        self._liked: list[Track] = []
        for i in range(70):
            # Liked music skews mid-tempo, with only a little at running cadence.
            bpm = rng.choice([rng.uniform(95, 140)] * 6 + [rng.uniform(140, 158)] * 2 + [rng.uniform(158, 166)])
            self._liked.append(Track(title=_song(rng), artists=[rng.choice(_ARTISTS)],
                                     duration_s=rng.randint(165, 290), video_id=f"demo{i:04d}",
                                     liked=True, bpm=round(bpm), bpm_source="demo"))
        self.saved: dict[str, list[str]] = {}

    def liked_tracks(self, limit: int = 5000) -> list[Track]:
        return [Track.from_dict(t.to_dict()) for t in self._liked[:limit]]

    def find_video(self, track: Track) -> str | None:
        return f"demo-rec-{abs(hash(track.key)) % 10**8}"

    def similar_tracks(self, seed: Track, limit: int = 40) -> list[Track]:
        return []

    def save_playlist(self, title, description, video_ids, privacy="PRIVATE", reuse=True) -> str:
        self.saved[title] = list(video_ids)
        return "demo-playlist"


class DemoCatalog:
    """Stands in for Deezer: artists, related artists and top tracks with BPM."""

    def __init__(self, seed: int = 11):
        rng = random.Random(seed)
        names = _ARTISTS + [s for v in _SIMILAR.values() for s in v]
        self.ids = {n: i + 1 for i, n in enumerate(names)}
        self.names = {i: n for n, i in self.ids.items()}
        self.tracks = {
            n: [{"id": self.ids[n] * 100 + k, "title": _song(rng), "artist": {"name": n},
                 "duration": rng.randint(170, 280), "bpm": round(rng.uniform(95, 188))} for k in range(12)]
            for n in names
        }

    def find_artist(self, name: str) -> dict | None:
        return {"id": self.ids[name], "name": name} if name in self.ids else None

    def related_artists(self, artist_id: int, limit: int = 10) -> list[dict]:
        name = self.names[artist_id]
        return [{"id": self.ids[s], "name": s} for s in _SIMILAR.get(name, [])][:limit]

    def top_tracks(self, artist_id: int, limit: int = 15) -> list[dict]:
        return self.tracks[self.names[artist_id]][:limit]

    def lookup(self, track: Track) -> float | None:  # BpmProvider
        return None
