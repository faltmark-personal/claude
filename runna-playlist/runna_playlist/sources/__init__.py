"""Where liked music comes from and where playlists are saved.

* ``youtube_data`` – official YouTube Data API v3 with Google OAuth (default).
* ``ytmusic``      – optional, unofficial ytmusicapi (browser-session auth).
* ``demo``         – built-in sample library, no account needed.
"""
from __future__ import annotations

from typing import Protocol

from ..models import Track


class MusicSource(Protocol):
    name: str
    official: bool

    def liked_tracks(self, limit: int = 5000) -> list[Track]: ...

    def find_video(self, track: Track) -> str | None:
        """Find the YouTube video id for a recommended track (None if not found)."""

    def similar_tracks(self, seed: Track, limit: int = 40) -> list[Track]:
        """Tracks similar to a seed (may return [] if the source can't do this)."""

    def save_playlist(self, title: str, description: str, video_ids: list[str],
                      privacy: str = "PRIVATE", reuse: bool = True) -> str:
        """Create or refill a playlist; returns its playlist id."""
