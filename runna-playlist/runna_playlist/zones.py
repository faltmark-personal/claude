"""Map heart-rate zones to music tempo (BPM) ranges.

Heart rate and music tempo are different things: a Z2 run at 140 bpm heart
rate does not call for 140 BPM music. The ranges here describe how energetic
the music should feel for each effort. For the hardest zones they're centred
on your running cadence, so you can step in time with the beat if you like.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Fractions of running cadence (steps/min) for each zone's (min, max) tempo.
CADENCE_FRACTIONS: dict[int, tuple[float, float]] = {
    1: (0.60, 0.74),  # recovery / warm-up / cool-down: relaxed
    2: (0.74, 0.86),  # easy aerobic: upbeat but not pushy
    3: (0.86, 0.97),  # tempo / steady: driving
    4: (0.97, 1.04),  # threshold: on the beat of your feet
    5: (1.04, 1.12),  # VO2 max / sprints: a little faster than your feet
}

ZONE_LABELS = {1: "Recovery", 2: "Easy", 3: "Tempo", 4: "Threshold", 5: "VO2 max"}


def ranges_from_cadence(spm: float) -> dict[int, tuple[float, float]]:
    return {z: (round(spm * lo), round(spm * hi)) for z, (lo, hi) in CADENCE_FRACTIONS.items()}


@dataclass
class ZoneMap:
    ranges: dict[int, tuple[float, float]] = field(default_factory=lambda: ranges_from_cadence(163))
    # Accept songs at half or double the target tempo (an 82 BPM song feels like 164).
    allow_half_double: bool = True

    def effective_bpm(self, bpm: float | None, zone: int) -> float | None:
        """The tempo a track would be felt at for this zone, or None if it doesn't fit."""
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
        mid, half = (lo + hi) / 2, ((hi - lo) / 2) or 1
        return max(0.0, 1 - abs(effective_bpm - mid) / half)

    def distance(self, bpm: float | None, zone: int) -> float:
        """How far (in BPM) a track is from the zone's range; 0 if it fits."""
        if not bpm:
            return float("inf")
        lo, hi = self.ranges[zone]
        options = [bpm] + ([bpm * 2, bpm / 2] if self.allow_half_double else [])
        return min(max(lo - c, 0, c - hi) for c in options)

    def to_dict(self) -> dict:
        return {
            "ranges": {str(z): list(r) for z, r in sorted(self.ranges.items())},
            "allow_half_double": self.allow_half_double,
        }

    @classmethod
    def from_dict(cls, d: dict | None) -> "ZoneMap":
        if not d:
            return cls()
        ranges = ranges_from_cadence(163)
        for key, val in (d.get("ranges") or {}).items():
            z = int(str(key).upper().removeprefix("Z"))
            lo, hi = (val["min"], val["max"]) if isinstance(val, dict) else val
            lo, hi = float(lo), float(hi)
            if not (z in ranges and 30 <= lo < hi <= 260):
                raise ValueError(f"Zone {z}: need 30 <= min < max <= 260")
            ranges[z] = (lo, hi)
        return cls(ranges=ranges, allow_half_double=bool(d.get("allow_half_double", True)))
