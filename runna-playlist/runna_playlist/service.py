"""App state and orchestration shared by the web API (single local user)."""
from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .bpm import BpmResolver, Deezer, build_providers
from .fit_import import ImportSettings
from .models import Track, Workout
from .planner import Plan, PlanItem, PlanOptions, alternatives, build_blocks, plan_playlist, retime
from .recommend import Recommender
from .zones import ZoneMap, ranges_from_cadence

log = logging.getLogger(__name__)

MODES = ("demo", "youtube_data", "ytmusic")


@dataclass
class Settings:
    mode: str = "demo"
    cadence_spm: int = 163
    zones: dict = field(default_factory=lambda: ZoneMap(ranges_from_cadence(163)).to_dict())
    min_block_s: int = 150
    merge_strategy: str = "weighted"
    slack_s: int = 30
    recommendations: bool = True
    analyze_previews: bool = False
    playlist_title: str = "Runna workout"
    reuse_playlist: bool = True
    privacy: str = "PRIVATE"
    max_hr: int = 190
    easy_pace: str = "6:00/km"
    hard_pace: str = "4:50/km"

    def zone_map(self) -> ZoneMap:
        return ZoneMap.from_dict(self.zones)

    def plan_options(self, seed: int | None = None) -> PlanOptions:
        return PlanOptions(min_block_s=self.min_block_s, merge_strategy=self.merge_strategy,
                           slack_s=self.slack_s, seed=seed)

    def import_settings(self) -> ImportSettings:
        from .workout import parse_pace_s_per_m

        return ImportSettings(max_hr=self.max_hr, easy_pace_s_per_km=parse_pace_s_per_m(self.easy_pace) * 1000,
                              hard_pace_s_per_km=parse_pace_s_per_m(self.hard_pace) * 1000)

    def validate(self) -> None:
        if self.mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}")
        if not 120 <= self.cadence_spm <= 220:
            raise ValueError("cadence should be 120-220 steps/min")
        if self.merge_strategy not in ("weighted", "max"):
            raise ValueError("merge_strategy must be 'weighted' or 'max'")
        if self.privacy not in ("PRIVATE", "UNLISTED", "PUBLIC"):
            raise ValueError("privacy must be PRIVATE, UNLISTED or PUBLIC")
        self.zone_map()
        self.import_settings()


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _write_json(path: Path, data: Any, private: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1))
    if private:
        tmp.chmod(0o600)
    tmp.replace(path)


class AppState:
    def __init__(self, data_dir: Path | str | None = None, base_url: str = "http://localhost:8765",
                 catalog=None, sources: dict | None = None):
        self.dir = Path(data_dir or os.environ.get("RUNNA_PLAYLIST_DATA") or Path.home() / ".runna-playlist")
        self.dir.mkdir(parents=True, exist_ok=True)
        self.base_url = base_url
        self.settings = Settings(**{k: v for k, v in _read_json(self.dir / "settings.json", {}).items()
                                    if k in Settings.__dataclass_fields__})
        self.overrides: dict[str, float] = _read_json(self.dir / "bpm_overrides.json", {})
        self.deezer = Deezer()
        self.catalog = catalog if catalog is not None else self.deezer
        self.resolver = BpmResolver(build_providers(self.deezer, self.settings.analyze_previews),
                                    self.overrides, self.dir / "bpm_cache.json")
        self._sources = sources or {}
        self.liked: dict[str, list[Track]] = {
            m: [Track.from_dict(d) for d in _read_json(self.dir / f"library_{m}.json", [])] for m in MODES
        }
        self.recs: dict[str, Track] = {d["key"]: Track.from_dict(d)
                                       for d in _read_json(self.dir / "recommendations.json", [])}
        # Old key -> new key, for recommendations re-keyed once found on YouTube.
        self.aliases: dict[str, str] = _read_json(self.dir / "aliases.json", {})
        self.sync_status: dict[str, Any] = {"running": False, "done": 0, "total": 0, "error": None}
        self._lock = threading.Lock()
        self._oauth = None

    # ---- settings -------------------------------------------------------
    def update_settings(self, patch: dict) -> Settings:
        data = asdict(self.settings)
        data.update({k: v for k, v in patch.items() if k in Settings.__dataclass_fields__})
        new = Settings(**data)
        new.validate()
        if new.analyze_previews != self.settings.analyze_previews:
            self.resolver.providers = build_providers(self.deezer, new.analyze_previews)
        self.settings = new
        _write_json(self.dir / "settings.json", asdict(new))
        return new

    # ---- sources --------------------------------------------------------
    @property
    def oauth(self):
        if self._oauth is None:
            from .sources.youtube_data import GoogleOAuth

            self._oauth = GoogleOAuth(self.dir / "google_client.json", self.dir / "google_token.json",
                                      f"{self.base_url}/api/auth/google/callback")
        return self._oauth

    def source(self, mode: str | None = None):
        mode = mode or self.settings.mode
        if mode in self._sources:
            return self._sources[mode]
        if mode == "demo":
            from .sources.demo import DemoSource

            self._sources["demo"] = DemoSource()
            return self._sources["demo"]
        if mode == "youtube_data":
            from .sources.youtube_data import YouTubeDataSource

            if not self.oauth.connected:
                raise PermissionError("Connect your Google account first (Settings → Official mode)")
            return YouTubeDataSource(self.oauth)
        if mode == "ytmusic":
            from .sources.ytmusic import YTMusicSource

            path = self.dir / "ytmusic_browser.json"
            if not path.exists():
                raise PermissionError("Set up ytmusicapi first (Settings → ytmusicapi mode)")
            src = YTMusicSource(path)
            self._sources["ytmusic"] = src
            return src
        raise ValueError(mode)

    def auth_status(self) -> dict:
        return {
            "mode": self.settings.mode,
            "google": {"configured": self.oauth.configured, "connected": self.oauth.connected},
            "ytmusic": {"connected": (self.dir / "ytmusic_browser.json").exists()},
            "intervals": {"connected": (self.dir / "intervals_key.json").exists()},
        }

    def _catalog(self):
        if self.settings.mode == "demo" and self.catalog is self.deezer:
            from .sources.demo import DemoCatalog

            if not hasattr(self, "_demo_catalog"):
                self._demo_catalog = DemoCatalog()
            return self._demo_catalog
        return self.catalog

    # ---- library --------------------------------------------------------
    def liked_tracks(self) -> list[Track]:
        tracks = self.liked[self.settings.mode]
        if not tracks and self.settings.mode == "demo":
            tracks = self.liked["demo"] = self.source("demo").liked_tracks()
        for t in tracks:  # apply overrides edited since the sync
            if t.key in self.overrides:
                t.bpm, t.bpm_source = float(self.overrides[t.key]), "manual"
        return tracks

    def start_sync(self, refresh_unknown: bool = False) -> None:
        with self._lock:
            if self.sync_status["running"]:
                return
            self.sync_status = {"running": True, "done": 0, "total": 0, "error": None}
        mode = self.settings.mode
        threading.Thread(target=self._sync, args=(mode, refresh_unknown), daemon=True).start()

    def _sync(self, mode: str, refresh_unknown: bool) -> None:
        try:
            tracks = self.source(mode).liked_tracks()
            self.sync_status["total"] = len(tracks)
            for i, t in enumerate(tracks):
                if mode == "demo":
                    if t.key in self.overrides:
                        t.bpm, t.bpm_source = float(self.overrides[t.key]), "manual"
                else:
                    self.resolver.resolve(t, refresh=refresh_unknown and t.key in self.resolver.cache
                                          and not self.resolver.cache[t.key]["bpm"])
                self.sync_status["done"] = i + 1
            self.resolver.save()
            self.liked[mode] = tracks
            _write_json(self.dir / f"library_{mode}.json", [t.to_dict() for t in tracks])
        except Exception as e:
            log.exception("Library sync failed")
            self.sync_status["error"] = str(e)
        finally:
            self.sync_status["running"] = False

    def set_bpm(self, key: str, bpm: float | None) -> None:
        if bpm is None:
            self.overrides.pop(key, None)
        else:
            if not 40 <= bpm <= 250:
                raise ValueError("BPM should be between 40 and 250")
            self.overrides[key] = float(bpm)
        _write_json(self.dir / "bpm_overrides.json", self.overrides)
        for t in list(self.liked_tracks()) + list(self.recs.values()):
            if t.key == key:
                if bpm is None:
                    t.bpm, t.bpm_source = None, None
                    self.resolver.cache.pop(key, None)
                    self.resolver._dirty += 1
                    self.resolver.resolve(t)
                else:
                    t.bpm, t.bpm_source = float(bpm), "manual"

    # ---- planning -------------------------------------------------------
    def pool(self) -> list[Track]:
        recs = list(self.recs.values())
        for t in recs:
            if t.key in self.overrides:
                t.bpm, t.bpm_source = float(self.overrides[t.key]), "manual"
        return self.liked_tracks() + recs

    def track(self, key: str) -> Track:
        key = self.aliases.get(key, key)
        for t in self.pool():
            if t.key == key:
                return t
        raise KeyError(f"Unknown track {key}")

    def make_plan(self, workout: Workout, locked: list[dict] | None = None, seed: int | None = None) -> Plan:
        zones = self.settings.zone_map()
        opts = self.settings.plan_options(seed)
        def locks() -> list[PlanItem]:
            return [PlanItem(track=self.track(x["key"]), block=int(x["block"]), locked=True)
                    for x in (locked or [])]

        plan = plan_playlist(workout, self.pool(), zones, opts, locks())
        if plan.shortfall_s and self.settings.recommendations:
            source = None
            try:
                source = self.source()
            except PermissionError:
                pass
            rec = Recommender(self._catalog(), self.resolver, zones, source)
            known = {t.key for t in self.pool()}
            for t in rec.recommend(self.liked_tracks(), plan.shortfall_s, known):
                self.recs[t.key] = t
            self._save_recs()
            plan = plan_playlist(workout, self.pool(), zones, opts, locks())
        return plan

    def _save_recs(self) -> None:
        _write_json(self.dir / "recommendations.json", [t.to_dict() for t in self.recs.values()])

    def items_from_payload(self, rows: list[dict]) -> list[PlanItem]:
        return [PlanItem(track=self.track(r["key"]), block=int(r["block"]), locked=bool(r.get("locked")))
                for r in rows]

    def retime(self, workout: Workout, rows: list[dict]) -> Plan:
        blocks = build_blocks(workout, self.settings.plan_options())
        items = self.items_from_payload(rows)
        for it in items:
            it.block = min(max(it.block, 0), len(blocks) - 1)
        retime(items, self.settings.zone_map(), blocks)
        return Plan(workout=workout, blocks=blocks, items=items)

    def alternatives(self, workout: Workout, rows: list[dict], index: int) -> list[dict]:
        plan = self.retime(workout, rows)
        used = {it.track.key for it in plan.items}
        return alternatives(plan.items[index], plan.blocks, self.pool(), used, self.settings.zone_map())

    # ---- saving ---------------------------------------------------------
    def save_playlist(self, workout: Workout, rows: list[dict], title: str | None = None) -> dict:
        source = self.source()
        plan = self.retime(workout, rows)
        missing = []
        for it in plan.items:
            if not it.track.video_id:
                vid = source.find_video(it.track)
                if vid:
                    # Re-key the recommendation under its YouTube id.
                    old = it.track.key
                    self.recs.pop(old, None)
                    it.track.video_id = vid
                    self.recs[it.track.key] = it.track
                    self.aliases[old] = it.track.key
                else:
                    missing.append(it.track.label)
        self._save_recs()
        _write_json(self.dir / "aliases.json", self.aliases)
        ids = [it.track.video_id for it in plan.items if it.track.video_id]
        title = title or self.settings.playlist_title
        description = describe(plan)
        pid = source.save_playlist(title, description, ids, self.settings.privacy, self.settings.reuse_playlist)
        return {"playlist_id": pid, "url": f"https://music.youtube.com/playlist?list={pid}",
                "saved": len(ids), "not_found": missing, "title": title, "plan": plan.to_dict()}


def fmt(s: int) -> str:
    s = int(round(s))
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


def describe(plan: Plan) -> str:
    parts = [f"{plan.workout.name} · {fmt(plan.workout.duration_s)}"]
    for b in plan.blocks:
        parts.append(f"{fmt(b.start_s)} Z{b.zone} {b.name}")
    text = "\n".join(parts) + "\nMade with runna-playlist. Turn shuffle off on your watch."
    return text[:4900]


def export_csv(plan: Plan) -> str:
    import csv
    import io

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["#", "start", "end", "block", "zone", "artist", "title", "duration", "bpm", "bpm_source",
                "effective_bpm", "in_zone", "from", "reason", "youtube_music_link"])
    for i, it in enumerate(plan.items, 1):
        t = it.track
        link = (f"https://music.youtube.com/watch?v={t.video_id}" if t.video_id else
                "https://music.youtube.com/search?q=" + __import__("urllib.parse").parse.quote(f"{t.artist} {t.title}"))
        b = plan.blocks[it.block]
        w.writerow([i, fmt(it.start_s), fmt(it.end_s), b.name, b.zone, t.artist, t.title, fmt(t.duration_s),
                    t.bpm or "", t.bpm_source or "", round(it.effective_bpm) if it.effective_bpm else "",
                    "yes" if it.in_zone else "NO", "liked" if t.liked else t.origin, t.reason, link])
    return buf.getvalue()
