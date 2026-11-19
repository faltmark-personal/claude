"""Integration code checked against stand-in HTTP/library clients (no network)."""
import json

from runna_playlist.bpm import BpmResolver, Deezer, clean_title
from runna_playlist.models import Track
from runna_playlist.sources.youtube_data import YouTubeDataSource, iso_duration, split_title
from runna_playlist.sources.ytmusic import YTMusicSource


class Resp:
    def __init__(self, data, status=200):
        self._d, self.status_code = data, status
        self.content = json.dumps(data).encode()
        self.text = self.content.decode()

    def json(self):
        return self._d

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class FakeOAuth:
    def access_token(self):
        return "tok"


class FakeHttp:
    def __init__(self, handler):
        self.handler, self.calls = handler, []

    def request(self, method, url, params=None, json=None, **kw):
        self.calls.append((method, url.rsplit("/", 1)[-1], params, json))
        return Resp(self.handler(method, url.rsplit("/", 1)[-1], params or {}, json))

    def get(self, url, params=None, **kw):
        return self.request("GET", url, params)


def test_helpers():
    assert iso_duration("PT3M45S") == 225 and iso_duration("PT1H2M") == 3720 and iso_duration("") == 0
    assert split_title("Daft Punk - Harder (Official Video)", "DaftPunkVEVO") == ("Harder", ["Daft Punk"])
    assert split_title("Song Name", "Some Artist - Topic") == ("Song Name", ["Some Artist"])
    assert clean_title("Song (feat. X) [Official Audio]") == "Song"


def test_youtube_data_likes_and_save():
    def handler(method, path, params, body):
        if path == "videos":
            return {"items": [
                {"id": "a1", "snippet": {"title": "Run Fast", "channelTitle": "Band - Topic", "categoryId": "10"},
                 "contentDetails": {"duration": "PT3M30S"}},
                {"id": "x9", "snippet": {"title": "Cat video", "channelTitle": "Cats", "categoryId": "15"},
                 "contentDetails": {"duration": "PT2M"}},
            ]}
        if path == "playlists" and method == "GET":
            return {"items": [{"id": "PL1", "snippet": {"title": "Runna workout"}}]}
        if path == "playlistItems" and method == "GET":
            return {"items": [{"id": "old1"}, {"id": "old2"}]}
        return {"id": "new"}

    http = FakeHttp(handler)
    src = YouTubeDataSource(FakeOAuth(), session=http)
    liked = src.liked_tracks()
    assert [(t.video_id, t.title, t.artists, t.duration_s) for t in liked] == [("a1", "Run Fast", ["Band"], 210)]

    pid = src.save_playlist("Runna workout", "desc", ["a1", "b2"], reuse=True)
    assert pid == "PL1"
    deletes = [c for c in http.calls if c[0] == "DELETE"]
    inserts = [c for c in http.calls if c[0] == "POST" and c[1] == "playlistItems"]
    assert len(deletes) == 2
    assert [c[3]["snippet"]["resourceId"]["videoId"] for c in inserts] == ["a1", "b2"]
    assert [c[3]["snippet"]["position"] for c in inserts] == [0, 1]


class FakeYT:
    def __init__(self):
        self.created = None

    def get_liked_songs(self, limit):
        return {"tracks": [
            {"videoId": "v1", "title": "Tempo", "artists": [{"name": "A", "id": "c1"}], "duration_seconds": 200},
            {"videoId": "v2", "title": "Intro", "artists": [{"name": "A"}], "duration": "0:40"},
            {"videoId": None, "title": "Gone"},
        ]}

    def get_watch_playlist(self, videoId, radio, limit):
        return {"tracks": [{"videoId": videoId, "title": "Tempo", "artists": [{"name": "A"}], "length": "3:20"},
                           {"videoId": "r1", "title": "Next", "artists": [{"name": "B"}], "length": "3:05"}]}

    def search(self, q, filter, limit):
        return [{"videoId": "s1", "title": "Next"}]

    def get_library_playlists(self, limit):
        return []

    def create_playlist(self, title, description, privacy_status, video_ids):
        self.created = (title, video_ids)
        return "PLx"


def test_ytmusic_source():
    yt = FakeYT()
    src = YTMusicSource(client=yt)
    liked = src.liked_tracks()
    assert [t.video_id for t in liked] == ["v1"]  # too-short and unavailable items dropped
    sim = src.similar_tracks(liked[0])
    assert [t.video_id for t in sim] == ["r1"] and sim[0].origin == "radio"
    assert src.find_video(Track("Next", ["B"], 185)) == "s1"
    assert src.save_playlist("W", "d", ["v1", "r1"], reuse=True) == "PLx" and yt.created == ("W", ["v1", "r1"])


def test_deezer_lookup_and_resolver_cache(tmp_path):
    def handler(method, path, params, body):
        if path == "search":
            return {"data": [{"id": 5, "title": "Harder", "artist": {"name": "Daft Punk"}, "duration": 224},
                             {"id": 6, "title": "Other", "artist": {"name": "Someone"}, "duration": 100}]}
        if path == "5":
            return {"id": 5, "bpm": 123.4, "preview": "http://p"}
        return {"error": "nope"}

    dz = Deezer(session=FakeHttp(handler))
    t = Track("Harder (Official Video)", ["Daft Punk"], 225, video_id="yt1")
    res = BpmResolver([dz], {}, tmp_path / "c.json")
    assert res.resolve(t) == 123.4 and t.bpm_source == "deezer"
    res.save()
    # Cached: a new resolver with no providers still knows it
    t2 = Track("Harder", ["Daft Punk"], 225, video_id="yt1")
    assert BpmResolver([], {}, tmp_path / "c.json").resolve(t2) == 123.4
    # Manual override wins
    assert BpmResolver([], {"yt1": 61.0}, tmp_path / "c.json").resolve(t2) == 61.0


def test_intervals_icu_import():
    from tests.test_fit import make_fit
    from runna_playlist.intervals_icu import IntervalsIcu

    fit = make_fit([{"duration_type": "time", "duration_value": 1200000, "target_type": "heart_rate",
                     "target_value": 3, "intensity": "active"}])

    class Http:
        def get(self, url, params=None, auth=None, timeout=None):
            assert auth == ("API_KEY", "k")
            if url.endswith("/events"):
                return Resp([{"id": 1, "name": "Tempo", "start_date_local": "2026-11-20T07:00:00", "type": "Run"},
                             {"id": 2, "name": "Ride", "type": "Ride"}])
            r = Resp({})
            r.content = bytes(fit)
            return r

    api = IntervalsIcu("k", session=Http())
    assert [e["name"] for e in api.planned_runs()] == ["Tempo"]
    w = api.workout(1)
    assert w.segments[0].zone == 3 and w.segments[0].duration_s == 1200
