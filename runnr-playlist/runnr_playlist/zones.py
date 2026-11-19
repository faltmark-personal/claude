"""Map heart-rate zones to music tempo (BPM) ranges."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

# Defaults follow the common pattern of easy running at lower tempos and
# hard efforts near running cadence (~165-185 steps/min). Override them in a
# zones YAML file to suit your own cadence and taste.
DEFAULT_ZONE_BPM: dict[int, tuple[float, float]] = {
    1: (100, 124),  # recovery / warm-up / cool-down
    2: (120, 140),  # easy aerobic
    3: (138, 156),  # tempo / steady
    4: (154, 172),  # threshold
    5: (168, 190),  # VO2 max / sprints
}


@dataclass
class ZoneMap:
    ranges: dict[int, tuple[float, float]]
    # Accept songs at half or double the target tempo (85 BPM feels like 170).
    allow_half_double: bool = True

    def range(self, zone: int) -> tuple[float, float]:
        return self.ranges[zone]

    def effective_bpm(self, bpm: float | None, zone: int) -> float | None:
        """Return the tempo the track would be felt at for this zone, or None."""
        if not bpm:
            return None
        lo, hi = self.ranges[zone]
        candidates = [bpm]
        if self.allow_half_double:
            candidates += [bpm * 2, bpm / 2]
        for c in candidates:
            if lo <= c <= hi:
                return c
        return None

    def fit_score(self, effective_bpm: float, zone: int) -> float:
        """1.0 at the centre of the zone's range, 0.0 at its edges."""
        lo, hi = self.ranges[zone]
        mid, half = (lo + hi) / 2, (hi - lo) / 2 or 1
        return max(0.0, 1 - abs(effective_bpm - mid) / half)


def load_zone_map(path: str | Path | None = None) -> ZoneMap:
    ranges = dict(DEFAULT_ZONE_BPM)
    allow = True
    if path:
        data = yaml.safe_load(Path(path).read_text()) or {}
        for key, val in (data.get("zones") or {}).items():
            zone = int(str(key).upper().removeprefix("Z"))
            lo, hi = (val["min"], val["max"]) if isinstance(val, dict) else val
            if lo >= hi:
                raise ValueError(f"Zone {zone}: min must be below max")
            ranges[zone] = (float(lo), float(hi))
        allow = bool(data.get("allow_half_double", True))
    return ZoneMap(ranges=ranges, allow_half_double=allow)
