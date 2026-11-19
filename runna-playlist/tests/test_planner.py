import random

from runna_playlist.models import Track
from runna_playlist.planner import PlanOptions, build_blocks, plan_playlist
from runna_playlist.workout import parse_spec
from runna_playlist.zones import ZoneMap, ranges_from_cadence

Z = ZoneMap(ranges_from_cadence(163))


def library(n=120, seed=3, bpm_range=(95, 185), liked=True, origin="liked"):
    rng = random.Random(seed)
    return [Track(title=f"Song {seed}-{i}", artists=[f"Artist {i % 9}"], duration_s=rng.randint(170, 290),
                  video_id=f"v{seed}-{i}", liked=liked, origin=origin, bpm=rng.uniform(*bpm_range), bpm_source="test")
            for i in range(n)]


def test_blocks_merge_short_intervals():
    w = parse_spec("Warm up: 10m@Z2, 8x(1m@Z5, 1m@Z1), 5x(4m@Z4, 90s@Z1), 8m@Z1")
    blocks = build_blocks(w, PlanOptions())
    fartlek = blocks[1]
    assert fartlek.merged and fartlek.duration_s == 16 * 60 and fartlek.zone == 3  # avg of Z5/Z1
    reps = blocks[2:7]
    assert all(b.zone == 4 and b.duration_s == 330 for b in reps)  # 90 s recovery folded into each rep
    assert build_blocks(w, PlanOptions(merge_strategy="max"))[1].zone == 5
    assert sum(b.duration_s for b in blocks) == w.duration_s


def test_plan_follows_zones_no_repeats_and_fits_duration():
    w = parse_spec("Warm up: 10m@Z2, 4x(5m@Z4, 2m@Z1), 6m@Z5, Cool down: 8m@Z1")
    plan = plan_playlist(w, library(300), Z, PlanOptions(seed=1))
    keys = [i.track.key for i in plan.items]
    assert len(keys) == len(set(keys))
    assert all(i.in_zone for i in plan.items)
    for it in plan.items:
        assert Z.effective_bpm(it.track.bpm, plan.blocks[it.block].zone)
    t = plan.timing()
    assert abs(t["difference_s"]) <= 60
    assert t["max_offset_s"] <= 90
    # Tempo follows the workout down as well as up
    zones = [plan.blocks[i.block].zone for i in plan.items]
    assert zones[0] == 2 and zones[-1] == 1 and 5 in zones


def test_liked_songs_preferred_over_recommendations():
    liked = library(60, seed=1, bpm_range=(120, 140))
    recs = library(60, seed=2, bpm_range=(120, 140), liked=False, origin="similar-artist")
    plan = plan_playlist(parse_spec("30m@Z2"), liked + recs, Z, PlanOptions(seed=4))
    assert all(i.track.liked for i in plan.items)


def test_shortfall_reported_and_closest_tempo_used():
    slow = library(40, bpm_range=(100, 125))
    plan = plan_playlist(parse_spec("10m@Z1, 10m@Z4"), slow, Z, PlanOptions(seed=1), )
    assert plan.shortfall_s.get(4, 0) > 0
    assert any(not i.in_zone for i in plan.items)
    assert all(i.in_zone for i in plan.items if plan.blocks[i.block].zone == 1)


def test_locked_tracks_kept():
    lib = library()
    from runna_playlist.planner import PlanItem

    pick = next(t for t in lib if Z.effective_bpm(t.bpm, 4))
    w = parse_spec("10m@Z2, 10m@Z4")
    plan = plan_playlist(w, lib, Z, PlanOptions(seed=9), [PlanItem(pick, block=1, locked=True)])
    assert pick.key in [i.track.key for i in plan.items if i.block == 1]
    assert [i.track.key for i in plan.items].count(pick.key) == 1


def test_running_out_of_songs_is_a_shortfall():
    few = [t for t in library(300) if Z.effective_bpm(t.bpm, 4)][:3]
    plan = plan_playlist(parse_spec("20m@Z4"), few, Z, PlanOptions(seed=1))
    assert plan.shortfall_s.get(4, 0) > 0
