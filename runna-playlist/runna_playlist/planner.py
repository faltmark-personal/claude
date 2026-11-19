"""Turn a workout and a pool of tracks into an ordered, timed playlist.

Whole songs only: the watch plays each song to the end and there's no
trimming, crossfading or timed switching. So music changes can only land
*near* segment boundaries. To keep errors from piling up, songs are planned
against the workout's absolute clock (each block ends at a fixed time from
the start), and every block reports how far its first song starts from the
real boundary.

Segments too short to hold a song are merged: a run of short intervals
(e.g. 8 x 1 min hard / 1 min easy) becomes one block with a blended zone,
and a single short segment (e.g. 90 s recovery) is folded into the block
before it.
"""
from __future__ import annotations

import itertools
import random
from dataclasses import dataclass, field
from typing import Any

from .models import Block, Track, Workout
from .zones import ZoneMap

ORIGIN_BONUS = {"liked": 10.0, "liked-artist": 3.0, "similar-artist": 2.0, "radio": 1.5}


@dataclass
class PlanOptions:
    min_block_s: int = 150      # segments shorter than this get merged
    merge_strategy: str = "weighted"  # "weighted" (time-weighted average zone) or "max"
    slack_s: int = 30           # a block counts as filled when within this of its end
    max_overshoot_s: int = 60   # a song may run this far past its block's end
    seed: int | None = None


@dataclass
class PlanItem:
    track: Track
    block: int
    start_s: int = 0
    effective_bpm: float | None = None
    in_zone: bool = True
    locked: bool = False

    @property
    def end_s(self) -> int:
        return self.start_s + self.track.duration_s

    def to_dict(self) -> dict[str, Any]:
        return {
            "track": self.track.to_dict(), "block": self.block, "start_s": self.start_s,
            "end_s": self.end_s, "effective_bpm": self.effective_bpm, "in_zone": self.in_zone,
            "locked": self.locked,
        }


@dataclass
class Plan:
    workout: Workout
    blocks: list[Block]
    items: list[PlanItem]
    shortfall_s: dict[int, int] = field(default_factory=dict)  # zone -> seconds with no in-zone song

    def timing(self) -> dict[str, Any]:
        return timing_report(self.workout, self.blocks, self.items)

    def to_dict(self) -> dict[str, Any]:
        return {
            "workout": self.workout.to_dict(),
            "blocks": [b.to_dict() for b in self.blocks],
            "items": [i.to_dict() for i in self.items],
            "shortfall_s": {str(k): v for k, v in self.shortfall_s.items()},
            "timing": self.timing(),
        }


def build_blocks(workout: Workout, opts: PlanOptions) -> list[Block]:
    segs = workout.segments
    starts, t = [], 0
    for s in segs:
        starts.append(t)
        t += s.duration_s

    def make(idx: list[int]) -> Block:
        first, last = segs[idx[0]], segs[idx[-1]]
        if len(idx) == 1:
            zone, name = first.zone, first.name
        else:
            if opts.merge_strategy == "max":
                zone = max(segs[i].zone for i in idx)
            else:
                total = sum(segs[i].duration_s for i in idx)
                zone = round(sum(segs[i].zone * segs[i].duration_s for i in idx) / total)
            name = f"{first.name} → {last.name}"
        return Block(name=name, start_s=starts[idx[0]], end_s=starts[idx[-1]] + last.duration_s,
                     zone=zone, segment_indexes=list(idx), merged=len(idx) > 1)

    short = [s.duration_s < opts.min_block_s for s in segs]
    groups: list[list[int]] = []
    i = 0
    while i < len(segs):
        if short[i] and i + 1 < len(segs) and short[i + 1]:
            j = i
            while j < len(segs) and short[j]:
                j += 1
            groups.append(list(range(i, j)))  # run of short intervals
            i = j
        elif short[i] and groups:
            groups[-1].append(i)  # lone short segment: fold into previous block
            i += 1
        elif short[i] and i + 1 < len(segs):
            groups.append([i, i + 1])  # short first segment: fold into the next one
            i += 2
        else:
            groups.append([i])
            i += 1
    blocks = [make(g) for g in groups]
    # A lone short segment folded into a long one keeps the long one's zone,
    # since it's mostly that effort.
    for b, g in zip(blocks, groups):
        if b.merged and not all(short[k] for k in g):
            longest = max(g, key=lambda k: segs[k].duration_s)
            b.zone, b.name = segs[longest].zone, f"{segs[longest].name} (+ {len(g) - 1} short)"
    return blocks


def _score(track: Track, eff: float, zone: int, zones: ZoneMap, prev: Track | None, rng: random.Random) -> float:
    s = ORIGIN_BONUS.get(track.origin, 1.0) + zones.fit_score(eff, zone) * 2 + rng.random() * 0.6
    if prev and set(prev.artists) & set(track.artists):
        s -= 1.5
    return s


def _closing_combo(fits, remaining: int, zone: int, zones: ZoneMap, prev: Track | None,
                   rng: random.Random, opts: PlanOptions):
    """Near the end of a block, pick the 1-3 songs whose total lands closest to the boundary.

    Preference still counts: each point of score is worth ~6 s of timing error,
    so a liked song (+10) beats a recommendation unless it's a minute worse.
    """
    if not fits:
        return None
    longest = max(t.duration_s for t, _ in fits)
    if remaining > 3 * longest:
        return None
    all_scored = [(t, e, _score(t, e, zone, zones, prev, rng)) for t, e in fits]
    # The best-scored songs, plus a spread of lengths so short gaps can be filled too.
    top = sorted(all_scored, key=lambda x: -x[2])[:16]
    by_len = sorted(all_scored, key=lambda x: x[0].duration_s)
    spread = by_len[:: max(1, len(by_len) // 8)][:8]
    scored = list({id(x): x for x in top + spread}.values())
    best, best_cost = None, None
    for r in (1, 2, 3):
        for combo in itertools.combinations(scored, r):
            total = sum(c[0].duration_s for c in combo)
            if total > remaining + opts.max_overshoot_s:
                continue
            cost = abs(remaining - total) - 6 * sum(c[2] for c in combo) / r
            if best_cost is None or cost < best_cost:
                best, best_cost = list(combo), cost
    if best is None:
        return None
    # Avoid same-artist neighbours inside the combo where possible.
    best.sort(key=lambda c: c[0].artist == (prev.artist if prev else None))
    return [(c[0], c[1]) for c in best]


def plan_playlist(workout: Workout, pool: list[Track], zones: ZoneMap, opts: PlanOptions | None = None,
                  locked: list[PlanItem] | None = None) -> Plan:
    opts = opts or PlanOptions()
    rng = random.Random(opts.seed)
    blocks = build_blocks(workout, opts)
    locked = locked or []
    used = {it.track.key for it in locked}
    with_bpm = [t for t in pool if t.bpm]
    items: list[PlanItem] = []
    shortfall: dict[int, int] = {}
    cursor = 0

    for bi, block in enumerate(blocks):
        z = block.zone
        for it in (x for x in locked if x.block == bi):
            it.start_s, cursor = cursor, cursor + it.track.duration_s
            it.effective_bpm = zones.effective_bpm(it.track.bpm, z)
            it.in_zone = it.effective_bpm is not None
            items.append(it)
        while block.end_s - cursor > opts.slack_s:
            remaining = block.end_s - cursor
            prev = items[-1].track if items else None
            cands = [(t, e) for t in with_bpm if t.key not in used and (e := zones.effective_bpm(t.bpm, z))]
            in_zone = True
            if not cands:
                # Nothing at this tempo: use the closest-tempo song we have and flag it.
                spare = [t for t in with_bpm if t.key not in used]
                if not spare:
                    shortfall[z] = shortfall.get(z, 0) + remaining
                    break
                best = min(spare, key=lambda t: (zones.distance(t.bpm, z), -ORIGIN_BONUS.get(t.origin, 1)))
                cands, in_zone = [(best, best.bpm)], False
            fits = [(t, e) for t, e in cands if t.duration_s <= remaining + opts.max_overshoot_s]
            combo = _closing_combo(fits, remaining, z, zones, prev, rng, opts) if in_zone else None
            if combo:
                for track, eff in combo:
                    used.add(track.key)
                    items.append(PlanItem(track=track, block=bi, start_s=cursor, effective_bpm=eff))
                    cursor += track.duration_s
                continue
            if fits:
                def key(te):
                    t, e = te
                    lands = abs(remaining - t.duration_s) <= opts.slack_s
                    return _score(t, e, z, zones, prev, rng) + (1.5 if lands else 0)
                track, eff = max(fits, key=key)
            else:
                # Every candidate is longer than what's left. Play one only if
                # most of it falls inside this block; otherwise let the next block start early.
                ok = [(t, e) for t, e in cands if remaining >= t.duration_s / 2]
                if not ok:
                    if not in_zone:  # ran out of songs at this tempo
                        shortfall[z] = shortfall.get(z, 0) + remaining
                    break
                track, eff = min(ok, key=lambda te: te[0].duration_s)
            if not in_zone:
                shortfall[z] = shortfall.get(z, 0) + min(track.duration_s, remaining)
            used.add(track.key)
            items.append(PlanItem(track=track, block=bi, start_s=cursor,
                                  effective_bpm=eff if in_zone else None, in_zone=in_zone))
            cursor += track.duration_s
    return Plan(workout=workout, blocks=blocks, items=items, shortfall_s=shortfall)


def retime(items: list[PlanItem], zones: ZoneMap, blocks: list[Block]) -> None:
    """Recompute start times and tempo fit after the user edits the list."""
    cursor = 0
    for it in items:
        it.start_s = cursor
        cursor += it.track.duration_s
        z = blocks[it.block].zone if 0 <= it.block < len(blocks) else blocks[-1].zone
        it.effective_bpm = zones.effective_bpm(it.track.bpm, z)
        it.in_zone = it.effective_bpm is not None


def block_at(blocks: list[Block], t: float) -> int:
    for i, b in enumerate(blocks):
        if b.start_s <= t < b.end_s:
            return i
    return len(blocks)  # after the workout ends


def timing_report(workout: Workout, blocks: list[Block], items: list[PlanItem]) -> dict[str, Any]:
    """How well music changes line up with the workout."""
    total = items[-1].end_s if items else 0
    rows = []
    for bi, b in enumerate(blocks):
        mine = [it for it in items if it.block == bi]
        first = mine[0].start_s if mine else None
        rows.append({
            "block": bi, "name": b.name, "zone": b.zone, "start_s": b.start_s, "end_s": b.end_s,
            "merged": b.merged, "songs": len(mine),
            "music_start_s": first,
            "offset_s": None if first is None else first - b.start_s,
            "music_s": sum(it.track.duration_s for it in mine),
        })
    drift = []
    for idx, it in enumerate(items):
        mid = it.start_s + it.track.duration_s / 2
        actual = block_at(blocks, mid)
        if actual != it.block:
            drift.append({"item": idx, "planned_block": it.block, "actual_block": actual})
    return {
        "workout_s": workout.duration_s,
        "playlist_s": total,
        "difference_s": total - workout.duration_s,
        "blocks": rows,
        "max_offset_s": max((abs(r["offset_s"]) for r in rows if r["offset_s"] is not None), default=0),
        "drifted_items": drift,
        "off_zone_items": [i for i, it in enumerate(items) if not it.in_zone],
    }


def alternatives(item: PlanItem, blocks: list[Block], pool: list[Track], used: set[str],
                 zones: ZoneMap, limit: int = 12) -> list[dict[str, Any]]:
    z = blocks[item.block].zone
    out = []
    for t in pool:
        if t.key in used or not t.bpm:
            continue
        eff = zones.effective_bpm(t.bpm, z)
        if eff is None:
            continue
        out.append({
            "track": t.to_dict(), "effective_bpm": eff,
            "duration_delta_s": t.duration_s - item.track.duration_s,
            "score": ORIGIN_BONUS.get(t.origin, 1) + zones.fit_score(eff, z) * 2
            - abs(t.duration_s - item.track.duration_s) / 60,
        })
    out.sort(key=lambda d: -d["score"])
    return out[:limit]
