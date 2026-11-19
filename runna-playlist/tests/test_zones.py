import pytest

from runna_playlist.zones import ZoneMap, ranges_from_cadence


def test_cadence_ranges_163():
    r = ranges_from_cadence(163)
    assert r[4][0] <= 163 <= r[4][1]  # threshold music sits on your cadence
    assert all(r[z][1] <= r[z + 1][0] + 1 for z in range(1, 5))  # ranges climb with effort


def test_half_double_time():
    z = ZoneMap({1: (98, 121), 2: (121, 140), 3: (140, 158), 4: (158, 170), 5: (170, 183)})
    assert z.effective_bpm(82, 4) == 164
    assert z.effective_bpm(164, 4) == 164
    assert z.effective_bpm(240, 2) == 120 or z.effective_bpm(240, 2) is None
    assert z.effective_bpm(None, 3) is None
    strict = ZoneMap(z.ranges, allow_half_double=False)
    assert strict.effective_bpm(82, 4) is None
    assert z.distance(150, 4) == 8 and z.distance(160, 4) == 0


def test_from_dict_validation():
    z = ZoneMap.from_dict({"ranges": {"Z2": [120, 135]}, "allow_half_double": False})
    assert z.ranges[2] == (120.0, 135.0) and not z.allow_half_double
    with pytest.raises(ValueError):
        ZoneMap.from_dict({"ranges": {"3": [150, 140]}})
