"""Workouts entered by hand (from a Runna session) as YAML/JSON, dicts or a compact text spec.

Each segment has a target heart-rate zone and either a duration or a
distance plus pace (Runna sessions are often written as "6 x 800m at 4:30/km")::

    name: Threshold intervals
    segments:
      - {name: Warm up, duration: 10m, zone: 2}
      - repeat: 4
        segments:
          - {name: Rep, distance: 1km, pace: "4:40/km", zone: 4}
          - {name: Recovery, duration: 90s, zone: 1}
      - {name: Cool down, duration: 8m, zone: 1}

Compact spec (used by the web app's quick entry)::

    Warm up: 10m@Z2, 4x(1km@4:40/km@Z4, Recovery: 90s@Z1), Cool down: 8m@Z1

Durations: ``90`` (seconds), ``mm:ss``, ``hh:mm:ss``, ``10m``, ``1h15m``, ``45s``.
Distances: ``800m``, ``5k``/``5km``, ``1mi``. Paces: ``4:30/km``, ``7:15/mi``.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

from .models import Segment, Workout

_UNIT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(hours?|hrs?|h|minutes?|mins?|m|seconds?|secs?|s)", re.I)
_DIST_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(km|k|mi|miles?|m)\s*$", re.I)
_PACE_RE = re.compile(r"^\s*(\d+):(\d{2})\s*/\s*(km|mi|mile)\s*$", re.I)


def parse_duration(value: Any) -> int:
    if isinstance(value, (int, float)):
        return int(round(value))
    text = str(value).strip().lower()
    if re.fullmatch(r"\d+(\.\d+)?", text):
        return int(round(float(text)))
    if ":" in text:
        parts = text.split(":")
        if len(parts) > 3 or not all(re.fullmatch(r"\d+(\.\d+)?", p) for p in parts):
            raise ValueError(f"Bad duration: {value!r}")
        seconds = 0.0
        for p in parts:
            seconds = seconds * 60 + float(p)
        return int(round(seconds))
    matches = _UNIT_RE.findall(text)
    if not matches or _UNIT_RE.sub("", text).strip():
        raise ValueError(f"Bad duration: {value!r}")
    seconds = 0.0
    for num, unit in matches:
        u = unit.lower()
        mult = 3600 if u.startswith("h") else 60 if u.startswith("m") else 1
        seconds += float(num) * mult
    return int(round(seconds))


def parse_distance_m(value: Any) -> float:
    m = _DIST_RE.match(str(value))
    if not m:
        raise ValueError(f"Bad distance: {value!r} (try 800m, 5km, 1mi)")
    num, unit = float(m.group(1)), m.group(2).lower()
    if unit in ("km", "k"):
        return num * 1000
    if unit.startswith("mi"):
        return num * 1609.344
    return num


def parse_pace_s_per_m(value: Any) -> float:
    m = _PACE_RE.match(str(value))
    if not m:
        raise ValueError(f"Bad pace: {value!r} (try 4:30/km or 7:15/mi)")
    secs = int(m.group(1)) * 60 + int(m.group(2))
    return secs / (1000 if m.group(3).lower() == "km" else 1609.344)

def parse_zone(value: Any) -> int:
    text = str(value).strip().upper().removeprefix("ZONE").removeprefix("Z").strip()
    zone = int(float(text))
    if not 1 <= zone <= 5:
        raise ValueError(f"Zone must be 1-5, got {value!r}")
    return zone


def infer_kind(name: str) -> str:
    n = name.lower()
    if "warm" in n:
        return "warmup"
    if "cool" in n:
        return "cooldown"
    if any(w in n for w in ("recover", "rest", "jog", "walk", "float")):
        return "recovery"
    return "work"


def _segment(item: dict, prefix: str) -> Segment:
    name = str(item.get("name") or f"Z{parse_zone(item['zone'])}")
    if item.get("duration") not in (None, ""):
        duration = parse_duration(item["duration"])
    elif item.get("distance") and item.get("pace"):
        duration = int(round(parse_distance_m(item["distance"]) * parse_pace_s_per_m(item["pace"])))
    else:
        raise ValueError(f"Segment {name!r} needs a duration, or a distance and pace")
    if duration <= 0:
        raise ValueError(f"Segment {name!r} has no length")
    return Segment(
        name=f"{prefix}{name}",
        duration_s=duration,
        zone=parse_zone(item["zone"]),
        kind=item.get("kind") or infer_kind(name),
    )


def _expand(items: list[dict], out: list[Segment], prefix: str = "") -> None:
    for item in items:
        if "repeat" in item:
            times = int(item["repeat"])
            if not 1 <= times <= 100:
                raise ValueError("repeat must be 1-100")
            for i in range(1, times + 1):
                _expand(item["segments"], out, prefix=f"{prefix}{i}/{times} ")
        else:
            out.append(_segment(item, prefix))


def workout_from_dict(data: dict) -> Workout:
    segments: list[Segment] = []
    _expand(data.get("segments") or [], segments)
    if not segments:
        raise ValueError("Workout has no segments")
    return Workout(name=data.get("name") or "Workout", segments=segments, description=data.get("description", ""))


def load_workout(path: str | Path) -> Workout:
    path = Path(path)
    text = path.read_text()
    data = json.loads(text) if path.suffix == ".json" else yaml.safe_load(text)
    return workout_from_dict(data)


def _split_top(s: str) -> list[str]:
    items, depth, buf = [], 0, ""
    for ch in s + ",":
        if ch in ",;\n" and depth == 0:
            if buf.strip():
                items.append(buf.strip())
            buf = ""
            continue
        depth += ch == "("
        depth -= ch == ")"
        if depth < 0:
            raise ValueError("Unbalanced parentheses")
        buf += ch
    if depth:
        raise ValueError("Unbalanced parentheses")
    return items


def _parse_spec_item(s: str) -> dict:
    m = re.fullmatch(r"(\d+)\s*[x×]\s*\((.*)\)", s, re.I | re.S)
    if m:
        return {"repeat": int(m.group(1)), "segments": [_parse_spec_item(x) for x in _split_top(m.group(2))]}
    name = None
    if ":" in s and "@" in s and not re.match(r"^\s*\d", s.split(":", 1)[0]):
        name, s = (p.strip() for p in s.split(":", 1))
    parts = [p.strip() for p in s.split("@")]
    if len(parts) not in (2, 3):
        raise ValueError(f"Expected <duration>@<zone> or <distance>@<pace>@<zone>, got {s!r}")
    item: dict = {"zone": parse_zone(parts[-1])}
    if name:
        item["name"] = name
    if len(parts) == 3:
        item["distance"], item["pace"] = parts[0], parts[1]
    else:
        item["duration"] = parts[0]
    return item


def parse_spec(spec: str, name: str = "Workout") -> Workout:
    """Parse e.g. ``"Warm up: 10m@Z2, 4x(1km@4:40/km@Z4, 90s@Z1), 8m@Z1"``."""
    return workout_from_dict({"name": name, "segments": [_parse_spec_item(x) for x in _split_top(spec)]})
