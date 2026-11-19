"""Load a workout (e.g. transcribed from a Runnr training guide) from YAML/JSON.

Format::

    name: Threshold intervals
    segments:
      - {name: Warm up, duration: 10m, zone: 2}
      - repeat: 4
        segments:
          - {name: Threshold, duration: "5:00", zone: 4}
          - {name: Recovery, duration: 2m, zone: 1}
      - {name: Cool down, duration: 8m, zone: 1}

Durations accept seconds (``90``), ``mm:ss`` / ``hh:mm:ss``, or unit strings
like ``10m``, ``1h15m``, ``45s``. Zones may be written ``3`` or ``Z3``.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

from .models import Segment, Workout

_UNIT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(h|hr|hrs|m|min|mins|s|sec|secs)", re.I)


def parse_duration(value: Any) -> int:
    if isinstance(value, (int, float)):
        return int(round(value))
    text = str(value).strip().lower()
    if re.fullmatch(r"\d+(\.\d+)?", text):
        return int(round(float(text)))
    if ":" in text:
        parts = [float(p) for p in text.split(":")]
        if len(parts) > 3:
            raise ValueError(f"Bad duration: {value!r}")
        seconds = 0.0
        for p in parts:
            seconds = seconds * 60 + p
        return int(round(seconds))
    matches = _UNIT_RE.findall(text)
    if not matches or _UNIT_RE.sub("", text).strip():
        raise ValueError(f"Bad duration: {value!r}")
    seconds = 0.0
    for num, unit in matches:
        mult = 3600 if unit.startswith("h") else 60 if unit.startswith("m") else 1
        seconds += float(num) * mult
    return int(round(seconds))


def parse_zone(value: Any) -> int:
    text = str(value).strip().upper().removeprefix("ZONE").removeprefix("Z").strip()
    zone = int(text)
    if not 1 <= zone <= 5:
        raise ValueError(f"Zone must be 1-5, got {value!r}")
    return zone


def _expand(items: list[dict], out: list[Segment], prefix: str = "") -> None:
    for item in items:
        if "repeat" in item:
            times = int(item["repeat"])
            for i in range(1, times + 1):
                _expand(item["segments"], out, prefix=f"{prefix}{i}/{times} ")
            continue
        out.append(
            Segment(
                name=f"{prefix}{item.get('name', 'Segment')}",
                duration_s=parse_duration(item["duration"]),
                zone=parse_zone(item["zone"]),
            )
        )


def workout_from_dict(data: dict) -> Workout:
    segments: list[Segment] = []
    _expand(data["segments"], segments)
    if not segments:
        raise ValueError("Workout has no segments")
    return Workout(
        name=data.get("name", "Workout"),
        segments=segments,
        description=data.get("description", ""),
    )


def load_workout(path: str | Path) -> Workout:
    path = Path(path)
    text = path.read_text()
    data = json.loads(text) if path.suffix == ".json" else yaml.safe_load(text)
    return workout_from_dict(data)


def parse_inline(spec: str, name: str = "Workout") -> Workout:
    """Parse a compact spec such as ``"10m@Z2, 4x(5m@Z4, 2m@Z1), 8m@Z1"``."""

    def parse_items(s: str) -> list[dict]:
        items, depth, buf = [], 0, ""
        for ch in s + ",":
            if ch == "," and depth == 0:
                if buf.strip():
                    items.append(parse_item(buf.strip()))
                buf = ""
                continue
            depth += ch == "("
            depth -= ch == ")"
            buf += ch
        return items

    def parse_item(s: str) -> dict:
        m = re.fullmatch(r"(\d+)\s*x\s*\((.*)\)", s, re.I | re.S)
        if m:
            return {"repeat": int(m.group(1)), "segments": parse_items(m.group(2))}
        if "@" not in s:
            raise ValueError(f"Expected <duration>@<zone>, got {s!r}")
        dur, zone = s.split("@", 1)
        z = parse_zone(zone)
        return {"name": f"Z{z}", "duration": dur.strip(), "zone": z}

    return workout_from_dict({"name": name, "segments": parse_items(spec)})
