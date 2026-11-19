"""YouTube Music access (via ytmusicapi) and discovery of similar music."""
from __future__ import annotations

import json
import logging
import os
from collections import Counter
from pathlib import Path
from typing import Any, Iterator

from .models import Track

log = logging.getLogger(__name__)


def _seconds(item: dict) -> int:
    if item.get("duration_seconds"):
        return int(item["duration_seconds"])
    text = item.get("duration") or item.get("length") or ""
    total = 0
    for part in str(text).split(":"):
        if not part.isdigit():
            return 0
        total = total * 60 + int(part)
    return total


def track_from_item(item: dict, liked: bool = False, origin: str = "liked") -> Track | None:
    if not item.get("videoId") or item.get("isAvailable") is False:
        return None
    artists = [a for a in (item.get("artists") or []) if a.get("name")]
    return Track(
        video_id=item["videoId"],
        title=item.get("title") or "",
        artists=[a["name"] for a in artists],
        artist_ids=[a["id"] for a in artists if a.get("id")],
        duration_s=_seconds(item),
        liked=liked,
        origin=origin,
    )


def connect(auth_path: str | Path) -> Any:
    """Open a YTMusic client from a browser.json or oauth.json auth file."""
    from ytmusicapi import YTMusic

    auth_path = Path(auth_path).expanduser()
    if not auth_path.exists():
        raise SystemExit(
            f"Auth file {auth_path} not found. Create one with `ytmusicapi browser` "
            "(see README: 'Connect YouTube Music')."
        )
    data = json.loads(auth_path.read_text())
    if "refresh_token" in data:
        from ytmusicapi import OAuthCredentials

        cid, secret = os.environ.get("YTM_CLIENT_ID"), os.environ.get("YTM_CLIENT_SECRET")
        if not (cid and secret):
            raise SystemExit("OAuth auth file needs YTM_CLIENT_ID and YTM_CLIENT_SECRET set.")
        return YTMusic(str(auth_path), oauth_credentials=OAuthCredentials(client_id=cid, client_secret=secret))
    return YTMusic(str(auth_path))


class MusicLibrary:
    def __init__(self, client: Any):
        self.yt = client

    def liked_tracks(self, limit: int = 5000) -> list[Track]:
        data = self.yt.get_liked_songs(limit=limit)
        tracks = [t for item in data.get("tracks", []) if (t := track_from_item(item, liked=True))]
        # Very short/long items are usually not songs (intros, mixes, podcasts).
        return [t for t in tracks if 60 <= t.duration_s <= 15 * 60]

    def radio(self, seed: Track, limit: int = 50) -> list[Track]:
        data = self.yt.get_watch_playlist(videoId=seed.video_id, radio=True, limit=limit)
        origin = f"radio:{seed.label}"
        return [t for item in data.get("tracks", []) if (t := track_from_item(item, origin=origin))]

    def related_artist_songs(self, artist_id: str, artist_name: str, max_artists: int = 5) -> list[Track]:
        artist = self.yt.get_artist(artist_id)
        related = (artist.get("related") or {}).get("results") or []
        out: list[Track] = []
        for rel in related[:max_artists]:
            if not rel.get("browseId"):
                continue
            try:
                songs = (self.yt.get_artist(rel["browseId"]).get("songs") or {}).get("results") or []
            except Exception as e:
                log.debug("get_artist(%s) failed: %s", rel.get("title"), e)
                continue
            origin = f"similar-artist:{rel.get('title')} (like {artist_name})"
            out += [t for item in songs if (t := track_from_item(item, origin=origin))]
        return out

    def write_playlist(
        self, title: str, description: str, video_ids: list[str], privacy: str = "PRIVATE", reuse: bool = False
    ) -> str:
        """Create a playlist, or with ``reuse`` replace the contents of one with the same title.

        Reusing keeps the playlist ID, so a Garmin watch that already syncs it
        just picks up the new songs on its next sync.
        """
        if reuse:
            for pl in self.yt.get_library_playlists(limit=None):
                if pl.get("title") == title:
                    pid = pl["playlistId"]
                    existing = self.yt.get_playlist(pid, limit=None).get("tracks") or []
                    if existing:
                        self.yt.remove_playlist_items(pid, existing)
                    self.yt.add_playlist_items(pid, video_ids, duplicates=False)
                    self.yt.edit_playlist(pid, description=description)
                    return pid
        pid = self.yt.create_playlist(title, description, privacy_status=privacy, video_ids=video_ids)
        if not isinstance(pid, str):
            raise RuntimeError(f"YouTube Music refused to create the playlist: {pid}")
        return pid


def discovery_candidates(
    library: MusicLibrary, seeds: list[Track], liked: list[Track], known_ids: set[str]
) -> Iterator[Track]:
    """Yield unseen tracks similar to the user's likes, most promising first.

    1. YouTube Music "radio" for each seed (seeds should be liked songs already
       in the target tempo range, so neighbours tend to share the feel).
       Tracks by artists the user already likes are yielded first.
    2. Top songs of artists related to the user's most-liked artists.
    """
    liked_artists = {a.lower() for t in liked for a in t.artists}
    seen = set(known_ids)

    def fresh(tracks: list[Track]) -> list[Track]:
        out = []
        for t in tracks:
            if t.video_id not in seen and 60 <= t.duration_s <= 10 * 60:
                seen.add(t.video_id)
                out.append(t)
        return out

    for seed in seeds:
        try:
            batch = fresh(library.radio(seed))
        except Exception as e:
            log.warning("Radio for %s failed: %s", seed.label, e)
            continue
        batch.sort(key=lambda t: not any(a.lower() in liked_artists for a in t.artists))
        yield from batch

    counts = Counter((t.artist_ids[0], t.artists[0]) for t in liked if t.artist_ids)
    for (artist_id, name), _ in counts.most_common(15):
        try:
            yield from fresh(library.related_artist_songs(artist_id, name))
        except Exception as e:
            log.warning("Related artists for %s failed: %s", name, e)
