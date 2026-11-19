"""Official YouTube Data API v3 source.

Liked music: the "Liked videos" list (``videos.list?myRating=like``). Songs you
like in YouTube Music are normally included; non-music videos are filtered out
by category. Playlists created here appear in YouTube Music's library.

Quota (default 10,000 units/day per Google Cloud project): reading likes costs
1 unit per 50 songs, creating a playlist 50, adding each song 50, and finding a
recommended song on YouTube 100. A 15-song workout playlist with 5
recommendations costs about 1,300 units.
"""
from __future__ import annotations

import json
import re
import secrets
import time
import urllib.parse
from pathlib import Path

import requests

from ..bpm import clean_artist, clean_title, similar
from ..models import Track

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
API = "https://www.googleapis.com/youtube/v3"
SCOPE = "https://www.googleapis.com/auth/youtube"
MUSIC_CATEGORY = "10"

_ISO = re.compile(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?")


def iso_duration(text: str) -> int:
    m = _ISO.fullmatch(text or "")
    if not m:
        return 0
    d, h, mi, s = (int(x or 0) for x in m.groups())
    return ((d * 24 + h) * 60 + mi) * 60 + s


def split_title(title: str, channel: str) -> tuple[str, list[str]]:
    """Best-effort artist/title split for music videos."""
    channel = clean_artist(channel)
    if " - " in title and not channel.endswith("VEVO"):
        left, right = title.split(" - ", 1)
        if similar(left, channel) > 0.6 or channel.lower() in left.lower():
            return clean_title(right), [left.strip()]
    channel = re.sub(r"VEVO$", "", channel).strip()
    if " - " in title:
        left, right = title.split(" - ", 1)
        return clean_title(right), [left.strip()]
    return clean_title(title), [channel]


class GoogleOAuth:
    """Installed-app OAuth for a single local user. Tokens live in ``token_path``."""

    def __init__(self, client_secrets: Path, token_path: Path, redirect_uri: str):
        self.client_secrets = client_secrets
        self.token_path = token_path
        self.redirect_uri = redirect_uri
        self._state: str | None = None

    def _client(self) -> dict:
        if not self.client_secrets.exists():
            raise FileNotFoundError(
                f"Put your Google OAuth client JSON at {self.client_secrets} (see README: 'Official mode setup')."
            )
        data = json.loads(self.client_secrets.read_text())
        return data.get("web") or data.get("installed") or data

    @property
    def configured(self) -> bool:
        return self.client_secrets.exists()

    @property
    def connected(self) -> bool:
        return self.token_path.exists()

    def start_url(self) -> str:
        c = self._client()
        self._state = secrets.token_urlsafe(16)
        params = {
            "client_id": c["client_id"], "redirect_uri": self.redirect_uri, "response_type": "code",
            "scope": SCOPE, "access_type": "offline", "prompt": "consent", "state": self._state,
        }
        return f"{AUTH_URL}?{urllib.parse.urlencode(params)}"

    def finish(self, code: str, state: str) -> None:
        if not self._state or state != self._state:
            raise PermissionError("OAuth state mismatch; start sign-in again")
        c = self._client()
        r = requests.post(TOKEN_URL, data={
            "code": code, "client_id": c["client_id"], "client_secret": c["client_secret"],
            "redirect_uri": self.redirect_uri, "grant_type": "authorization_code",
        }, timeout=20)
        r.raise_for_status()
        tok = r.json()
        tok["expires_at"] = time.time() + tok.get("expires_in", 3600) - 60
        self.token_path.parent.mkdir(parents=True, exist_ok=True)
        self.token_path.write_text(json.dumps(tok))
        self.token_path.chmod(0o600)
        self._state = None

    def access_token(self) -> str:
        tok = json.loads(self.token_path.read_text())
        if time.time() >= tok.get("expires_at", 0):
            c = self._client()
            r = requests.post(TOKEN_URL, data={
                "client_id": c["client_id"], "client_secret": c["client_secret"],
                "refresh_token": tok["refresh_token"], "grant_type": "refresh_token",
            }, timeout=20)
            r.raise_for_status()
            tok.update(r.json())
            tok["expires_at"] = time.time() + tok.get("expires_in", 3600) - 60
            self.token_path.write_text(json.dumps(tok))
        return tok["access_token"]

    def disconnect(self) -> None:
        self.token_path.unlink(missing_ok=True)


class YouTubeDataSource:
    name = "youtube_data"
    official = True

    def __init__(self, oauth: GoogleOAuth, session: requests.Session | None = None):
        self.oauth = oauth
        self.http = session or requests.Session()

    def _call(self, method: str, path: str, params: dict | None = None, body: dict | None = None) -> dict:
        r = self.http.request(
            method, f"{API}/{path}", params=params, json=body, timeout=20,
            headers={"Authorization": f"Bearer {self.oauth.access_token()}"},
        )
        if r.status_code == 403 and "quota" in r.text.lower():
            raise RuntimeError("YouTube Data API daily quota used up; try again tomorrow or use ytmusicapi mode")
        r.raise_for_status()
        return r.json() if r.content else {}

    def liked_tracks(self, limit: int = 5000) -> list[Track]:
        out: list[Track] = []
        page = None
        while len(out) < limit:
            params = {"part": "snippet,contentDetails", "myRating": "like", "maxResults": 50}
            if page:
                params["pageToken"] = page
            data = self._call("GET", "videos", params)
            for v in data.get("items", []):
                sn = v["snippet"]
                if sn.get("categoryId") != MUSIC_CATEGORY:
                    continue
                dur = iso_duration(v["contentDetails"].get("duration", ""))
                if not 60 <= dur <= 15 * 60:
                    continue
                title, artists = split_title(sn["title"], sn.get("channelTitle", ""))
                out.append(Track(title=title, artists=artists, duration_s=dur, video_id=v["id"], liked=True))
            page = data.get("nextPageToken")
            if not page:
                break
        return out[:limit]

    def find_video(self, track: Track) -> str | None:
        data = self._call("GET", "search", {
            "part": "snippet", "type": "video", "videoCategoryId": MUSIC_CATEGORY, "maxResults": 5,
            "q": f"{track.artists[0] if track.artists else ''} {clean_title(track.title)}",
        })
        for item in data.get("items", []):
            title, artists = split_title(item["snippet"]["title"], item["snippet"].get("channelTitle", ""))
            if similar(title, clean_title(track.title)) > 0.6:
                return item["id"]["videoId"]
        items = data.get("items") or []
        return items[0]["id"]["videoId"] if items else None

    def similar_tracks(self, seed: Track, limit: int = 40) -> list[Track]:
        return []  # related-video search was removed from the Data API in 2023

    def save_playlist(self, title: str, description: str, video_ids: list[str],
                      privacy: str = "PRIVATE", reuse: bool = True) -> str:
        pid = None
        if reuse:
            page = None
            while pid is None:
                params = {"part": "snippet", "mine": "true", "maxResults": 50}
                if page:
                    params["pageToken"] = page
                data = self._call("GET", "playlists", params)
                pid = next((p["id"] for p in data.get("items", []) if p["snippet"]["title"] == title), None)
                page = data.get("nextPageToken")
                if not page:
                    break
        if pid:
            self._call("PUT", "playlists", {"part": "snippet"},
                       {"id": pid, "snippet": {"title": title, "description": description}})
            page = None
            while True:  # clear existing items
                params = {"part": "id", "playlistId": pid, "maxResults": 50}
                if page:
                    params["pageToken"] = page
                data = self._call("GET", "playlistItems", params)
                for it in data.get("items", []):
                    self._call("DELETE", "playlistItems", {"id": it["id"]})
                page = data.get("nextPageToken")
                if not page:
                    break
        else:
            pid = self._call("POST", "playlists", {"part": "snippet,status"}, {
                "snippet": {"title": title, "description": description},
                "status": {"privacyStatus": privacy.lower()},
            })["id"]
        for pos, vid in enumerate(video_ids):
            self._call("POST", "playlistItems", {"part": "snippet"}, {"snippet": {
                "playlistId": pid, "position": pos, "resourceId": {"kind": "youtube#video", "videoId": vid},
            }})
        return pid
