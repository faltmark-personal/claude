"""Import planned workouts from Intervals.icu with your personal API key.

Intervals.icu (intervals.icu) holds a training calendar that plans and
coaches can fill. It can also receive workouts from other tools and send
them to Garmin. Its API accepts a personal key (Settings → Developer
Settings) with HTTP basic auth, user ``API_KEY``. Each planned workout is
downloaded as a FIT workout file and read by :mod:`fit_import`.
"""
from __future__ import annotations

import datetime as dt

import requests

from .fit_import import ImportSettings, workout_from_fit
from .models import Workout

BASE = "https://intervals.icu/api/v1"


class IntervalsIcu:
    def __init__(self, api_key: str, athlete_id: str = "0", session: requests.Session | None = None):
        self.auth = ("API_KEY", api_key)
        self.athlete = athlete_id  # "0" means the key's own athlete
        self.http = session or requests.Session()

    def planned_runs(self, days: int = 14) -> list[dict]:
        today = dt.date.today()
        r = self.http.get(f"{BASE}/athlete/{self.athlete}/events", auth=self.auth, timeout=20, params={
            "oldest": today.isoformat(), "newest": (today + dt.timedelta(days=days)).isoformat(),
            "category": "WORKOUT",
        })
        r.raise_for_status()
        return [
            {"id": e["id"], "name": e.get("name") or "Workout", "date": (e.get("start_date_local") or "")[:10],
             "type": e.get("type"), "moving_time": e.get("moving_time")}
            for e in r.json() if (e.get("type") or "Run") in ("Run", "VirtualRun", "TrailRun")
        ]

    def workout(self, event_id: int | str, cfg: ImportSettings | None = None) -> Workout:
        r = self.http.get(f"{BASE}/athlete/{self.athlete}/events/{event_id}/download.fit",
                          auth=self.auth, timeout=30)
        r.raise_for_status()
        return workout_from_fit(r.content, cfg)
