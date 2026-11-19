from garmin_fit_sdk import Encoder, Profile

from runna_playlist.fit_import import ImportSettings, workout_from_fit

M = Profile["mesg_num"]


def make_fit(steps):
    e = Encoder()
    e.on_mesg(M["FILE_ID"], {"type": "workout", "manufacturer": "development", "product": 0,
                             "time_created": 1000000000, "serial_number": 1})
    e.on_mesg(M["WORKOUT"], {"wkt_name": "Imported", "sport": "running", "num_valid_steps": len(steps)})
    for i, s in enumerate(steps):
        e.on_mesg(M["WORKOUT_STEP"], {"message_index": i, **s})
    return e.close()


def test_fit_zones_repeats_and_guesses():
    data = make_fit([
        {"wkt_step_name": "Warm up", "duration_type": "time", "duration_value": 600000,
         "target_type": "heart_rate", "target_value": 2, "intensity": "warmup"},
        # 1 km with a custom HR range of 155-170 bpm (FIT stores bpm + 100)
        {"duration_type": "distance", "duration_value": 100000, "target_type": "heart_rate",
         "target_value": 0, "custom_target_value_low": 255, "custom_target_value_high": 270, "intensity": "active"},
        {"duration_type": "time", "duration_value": 90000, "target_type": "open", "intensity": "recovery"},
        {"duration_type": "repeat_until_steps_cmplt", "duration_value": 1, "target_value": 3},
        {"duration_type": "open", "target_type": "open", "intensity": "cooldown"},
    ])
    w = workout_from_fit(data, ImportSettings(max_hr=190, hard_pace_s_per_km=300))
    assert w.name == "Imported"
    assert [s.zone for s in w.segments] == [2, 4, 1, 4, 1, 4, 1, 1]
    assert w.segments[1].duration_s == 300  # 1 km at the hard pace
    assert w.segments[1].name.startswith("1/3")
    assert "guessed" in w.segments[2].note
    assert "open-ended" in w.segments[-1].note


def test_not_a_workout():
    import pytest

    with pytest.raises(ValueError):
        workout_from_fit(make_fit([]))
