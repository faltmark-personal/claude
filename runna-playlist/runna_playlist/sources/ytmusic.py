"""Optional, UNOFFICIAL YouTube Music source using ytmusicapi.

ytmusicapi imitates the YouTube Music web client using your browser session.
It isn't supported by Google, may break when YouTube changes its site, and
using it may not be permitted by YouTube's terms. Upside: it reads YouTube
Music likes directly, has no daily quota and offers "song radio" for finding
similar music.

Auth: in the web app, paste the request headers from a logged-in
music.youtube.com tab (see README), which runs ``ytmusicapi.setup`` and
writes ``browser.json`` to the data directory.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ..bpm import clean_title, similar
from ..models import Track


def _seconds(item: dict) -> int:
    if item.get("duration_seconds"):
        return int(item["duration_seconds"])
    total = 0
    for part in str(item.get("duration") or item.get("length") or "").split(":"):
        if not part.isdigit():
            return 0
        total = total * 60 + int(part)
    return total


def track_from_item(item: dict, **kw) -> Track | None:
    if not item.get("videoId") or item.get("isAvailable") is False:
        return None
    return Track(
        title=item.get("title") or "",
        artists=[a["name"] for a in (item.get("artists") or []) if a.get("name")],
        duration_s=_seconds(item),
        video_id=item["videoId"],
        **kw,
    )


def setup_from_headers(headers_raw: str, path: Path) -> None:
    import ytmusicapi

    path.parent.mkdir(parents=True, exist_ok=True)
    ytmusicapi.setup(filepath=str(path), headers_raw=headers_raw)
    path.chmod(0o600)


class YTMusicSource:
    name = "ytmusic"
    official = False

    def __init__(self, auth_path: Path | None = None, client: Any = None):
        if client is None:
            from ytmusicapi import YTMusic

            client = YTMusic(str(auth_path))
        self.yt = client

    def liked_tracks(self, limit: int = 5000) -> list[Track]:
        data = self.yt.get_liked_songs(limit=limit)
        tracks = [t for it in data.get("tracks", []) if (t := track_from_item(it, liked=True))]
        return [t for t in tracks if 60 <= t.duration_s <= 15 * 60]

    def find_video(self, track: Track) -> str | None:
        q = f"{track.artists[0] if track.artists else ''} {clean_title(track.title)}"
        for r in self.yt.search(q, filter="songs", limit=5):
            if r.get("videoId") and similar(r.get("title", ""), clean_title(track.title)) > 0.6:
                return r["videoId"]
        return None

    def similar_tracks(self, seed: Track, limit: int = 40) -> list[Track]:
        if not seed.video_id:
            return []
        data = self.yt.get_watch_playlist(videoId=seed.video_id, radio=True, limit=limit)
        return [t for it in data.get("tracks", [])
                if (t := track_from_item(it, origin="radio", reason=f"Song radio from {seed.label}"))
                and t.video_id != seed.video_id]

    def save_playlist(self, title: str, description: str, video_ids: list[str],
                      privacy: str = "PRIVATE", reuse: bool = True) -> str:
        if reuse:
            for pl in self.yt.get_library_playlists(limit=None):
                if pl.get("title") == title:
                    pid = pl["playlistId"]
                    existing = self.yt.get_playlist(pid, limit=None).get("tracks") or []
                    if existing:
                        self.yt.remove_playlist_items(pid, existing)
                    self.yt.add_playlist_items(pid, video_ids, duplicates=True)
                    self.yt.edit_playlist(pid, description=description)
                    return pid
        pid = self.yt.create_playlist(title, description, privacy_status=privacy, video_ids=video_ids)
        if not isinstance(pid, str):
            raise RuntimeError(f"YouTube Music refused to create the playlist: {pid}")
        return pid
