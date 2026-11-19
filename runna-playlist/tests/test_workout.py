import pytest

from runna_playlist.workout import parse_duration, parse_spec, workout_from_dict


@pytest.mark.parametrize("text,secs", [
    ("90", 90), (90, 90), ("4:30", 270), ("1:02:03", 3723), ("10m", 600), ("1h15m", 4500),
    ("45s", 45), ("2 min", 120), ("1.5m", 90),
])
def test_durations(text, secs):
    assert parse_duration(text) == secs


@pytest.mark.parametrize("bad", ["abc", "10x", "1:2:3:4", "m"])
def test_bad_durations(bad):
    with pytest.raises(ValueError):
        parse_duration(bad)


def test_spec_with_repeats_names_and_distance():
    w = parse_spec("Warm up: 10m@Z2, 3x(1km@4:40/km@Z4, Recovery: 90s@Z1), Cool down: 8m@Z1")
    assert [s.zone for s in w.segments] == [2, 4, 1, 4, 1, 4, 1, 1]
    assert w.segments[1].duration_s == 280  # 1 km at 4:40/km
    assert w.segments[0].kind == "warmup" and w.segments[2].kind == "recovery"
    assert w.segments[2].name == "1/3 Recovery"
    assert w.duration_s == 600 + 3 * 370 + 480


def test_spec_miles_and_nested_repeat():
    w = parse_spec("2x(2x(400m@7:00/mi@Z5, 1m@Z1), 3m@Z2)")
    assert len(w.segments) == 2 * (2 * 2 + 1)
    assert w.segments[0].duration_s == round(400 / 1609.344 * 420)


def test_dict_workout_and_errors():
    w = workout_from_dict({"name": "X", "segments": [{"duration": "5:00", "zone": "Z3"}]})
    assert w.segments[0].zone == 3
    with pytest.raises(ValueError):
        workout_from_dict({"segments": [{"duration": "5m", "zone": 7}]})
    with pytest.raises(ValueError):
        workout_from_dict({"segments": [{"zone": 2}]})
    with pytest.raises(ValueError):
        parse_spec("5x(1m@Z4")
