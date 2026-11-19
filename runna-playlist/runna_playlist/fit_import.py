"""Import structured workouts from Garmin FIT workout files.

FIT workout files are what Garmin Connect sends to the watch. TrainingPeaks
and other planners can export them too. Steps may target a heart-rate zone,
a custom heart-rate range, a pace range or nothing ("open"):

* HR zone targets are used as-is.
* Custom HR ranges are mapped to zones using your max HR and zone boundaries.
* Pace/open targets get a zone guessed from the step type (warm-up, interval,
  recovery...) and are flagged so you can check them in the editor.
* Distance steps are converted to time using the step's pace target, or
  your easy/hard paces from settings.
"""
from __future__ import annotations

from dataclasses import dataclass

from .models import Segment, Workout

# Garmin's default zones, as % of max HR: Z1 50-60, Z2 60-70, Z3 70-80, Z4 80-90, Z5 90+.
DEFAULT_ZONE_FLOORS_PCT = (50, 60, 70, 80, 90)

GUESS_BY_INTENSITY = {"warmup": 2, "cooldown": 1, "recovery": 1, "rest": 1, "active": 4, "interval": 4, "other": 2}
KIND_BY_INTENSITY = {"warmup": "warmup", "cooldown": "cooldown", "recovery": "recovery", "rest": "recovery"}


@dataclass
class ImportSettings:
    max_hr: int = 190
    zone_floors_pct: tuple[int, ...] = DEFAULT_ZONE_FLOORS_PCT
    easy_pace_s_per_km: float = 360  # used for distance steps with no pace target
    hard_pace_s_per_km: float = 290

    def zone_for_bpm(self, bpm: float) -> int:
        pct = bpm / self.max_hr * 100
        zone = 1
        for z, floor in enumerate(self.zone_floors_pct, start=1):
            if pct >= floor:
                zone = z
        return zone


def _hr_bpm(v: float) -> float:
    """FIT encodes custom HR as %max (0-100) or bpm + 100."""
    return v - 100 if v > 100 else v


def _zone(step: dict, cfg: ImportSettings) -> tuple[int, str]:
    if step.get("target_type") == "heart_rate":
        if step.get("target_hr_zone"):
            return max(1, min(5, int(step["target_hr_zone"]))), ""
        lo, hi = step.get("custom_target_heart_rate_low"), step.get("custom_target_heart_rate_high")
        if lo and hi:
            lo_v, hi_v = _hr_bpm(lo), _hr_bpm(hi)
            if lo <= 100:  # percentages
                lo_v, hi_v = lo_v * cfg.max_hr / 100, hi_v * cfg.max_hr / 100
            return cfg.zone_for_bpm((lo_v + hi_v) / 2), f"HR {round(lo_v)}-{round(hi_v)} bpm"
    intensity = str(step.get("intensity") or "active")
    return GUESS_BY_INTENSITY.get(intensity, 3), "zone guessed from step type; please check"


def _duration(step: dict, cfg: ImportSettings) -> int | None:
    if step.get("duration_type") in ("time", "time_only", "repetition_time"):
        return int(round(step.get("duration_time") or step.get("duration_value", 0) / 1000))
    if step.get("duration_type") == "distance":
        metres = step.get("duration_distance") or step.get("duration_value", 0) / 100
        lo, hi = step.get("custom_target_speed_low"), step.get("custom_target_speed_high")
        if step.get("target_type") == "speed" and lo and hi:
            speed = (lo + hi) / 2  # m/s
            return int(round(metres / speed))
        hard = str(step.get("intensity")) in ("active", "interval")
        pace = cfg.hard_pace_s_per_km if hard else cfg.easy_pace_s_per_km
        return int(round(metres / 1000 * pace))
    return None  # open / lap-button / HR-until steps


def workout_from_fit(data: bytes, cfg: ImportSettings | None = None, open_step_s: int = 300) -> Workout:
    from garmin_fit_sdk import Decoder, Stream

    cfg = cfg or ImportSettings()
    messages, errors = Decoder(Stream.from_byte_array(bytearray(data))).read()
    if errors:
        raise ValueError(f"Could not read FIT file: {errors[0]}")
    steps = sorted(messages.get("workout_step_mesgs") or [], key=lambda m: m.get("message_index", 0))
    if not steps:
        raise ValueError("No workout steps in this FIT file (is it a workout, not an activity?)")
    name = ((messages.get("workout_mesgs") or [{}])[0]).get("wkt_name") or "Imported workout"

    def build(i: int) -> list[Segment]:
        st = steps[i]
        zone, note = _zone(st, cfg)
        dur = _duration(st, cfg)
        if dur is None:
            dur, note = open_step_s, (note + "; " if note else "") + "open-ended step, assumed 5 min"
        intensity = str(st.get("intensity") or "active")
        label = st.get("wkt_step_name") or intensity.replace("_", " ").title()
        return [Segment(name=label, duration_s=dur, zone=zone,
                        kind=KIND_BY_INTENSITY.get(intensity, "work"), note=note)]

    out: list[Segment] = []
    by_index: dict[int, list[Segment]] = {}
    for i, st in enumerate(steps):
        if str(st.get("duration_type", "")).startswith("repeat_until_steps"):
            start = int(st.get("duration_step", st.get("duration_value", 0)))
            times = int(st.get("repeat_steps", st.get("target_value", 1)))
            block = [seg for j in range(start, i) for seg in by_index.get(j, [])]
            # The block has already been emitted once; add the remaining repetitions.
            for rep in range(2, times + 1):
                out.extend(Segment(f"{rep}/{times} {s.name}", s.duration_s, s.zone, s.kind, s.note) for s in block)
            # Tag the first pass too
            first = len(out) - len(block) * times
            for k, s in enumerate(out[first:first + len(block)]):
                s.name = f"1/{times} {s.name}"
            by_index[i] = []
            continue
        segs = build(i)
        by_index[i] = segs
        out.extend(segs)
    return Workout(name=name, segments=out)
