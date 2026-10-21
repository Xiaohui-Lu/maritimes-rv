"""Matching tows to the CTD cast made at the same station. Positions are near 44 N, where 0.01 degree
of latitude is 1.11 km; the tow below starts at 12:00 local (ADT), lasts 30 minutes, so it ends at
15:30 UTC at (44.02, -63.0)."""
import pandas as pd
import pytest

from maritimes_rv import temperature


def tows(**overrides):
    row = {
        "mission": "NED2016016", "setno": 5, "year": 2016,
        "start_datetime_local": pd.Timestamp("2016-07-01 12:00"), "duration_min": 30,
        "start_lat": 44.0, "start_lon": -63.0, "end_lat": 44.02, "end_lon": -63.0, "bottom_temp_c": None,
    }
    frame = pd.DataFrame([row | overrides])
    return frame.astype({"setno": "Int16", "year": "Int16", "duration_min": "Int16", "start_lat": "Float64",
                         "start_lon": "Float64", "end_lat": "Float64", "end_lon": "Float64", "bottom_temp_c": "Float64"})


def casts(*rows):
    """rows: (profile_id, utc time, lat, lon, temp[, flag])."""
    frame = pd.DataFrame(
        [(r[0], pd.Timestamp(r[1]), r[2], r[3], r[4], r[5] if len(r) > 5 else 1) for r in rows],
        columns=["profile_id", "time_utc", "lat", "lon", "bottom_temp_c", "temp_flag"],
    )
    return frame.astype({"profile_id": "string", "lat": "Float64", "lon": "Float64",
                         "bottom_temp_c": "Float64", "temp_flag": "Int8"})


def merged(tow, cast_table):
    return temperature.add_ctd_temperature(tow, cast_table).iloc[0]


def test_cast_at_the_tow_end_fills_a_missing_temperature():
    row = merged(tows(), casts(("CTD_X_001_1_DN", "2016-07-01 15:45", 44.025, -63.0, 6.5)))  # 0.56 km, 15 min
    assert row["bottom_temp_merged_c"] == 6.5
    assert (row["bottom_temp_source"], row["ctd_match"]) == ("ctd", "position")
    assert row["ctd_distance_km"] == pytest.approx(0.556, abs=0.01)


def test_survey_reading_is_kept_and_compared():
    agree = merged(tows(bottom_temp_c=6.4), casts(("C", "2016-07-01 15:45", 44.025, -63.0, 6.5)))
    assert (agree["bottom_temp_merged_c"], agree["bottom_temp_source"], agree["qc_ctd_temp_mismatch"]) == (6.4, "survey", False)
    differ = merged(tows(bottom_temp_c=4.0), casts(("C", "2016-07-01 15:45", 44.025, -63.0, 6.5)))
    assert differ["bottom_temp_merged_c"] == 4.0 and differ["qc_ctd_temp_mismatch"]


@pytest.mark.parametrize("cast", [
    ("C", "2016-07-01 18:00", 44.025, -63.0, 6.5),     # 2.5 hours after the tow ends
    ("C", "2016-07-01 15:45", 44.05, -63.0, 6.5),      # 3.3 km from the tow's end
    ("C", "2016-07-01 15:45", 44.025, -63.0, 6.5, 4),  # flagged erroneous
])
def test_casts_too_late_too_far_or_flagged_are_not_used(cast):
    row = merged(tows(), casts(cast))
    assert pd.isna(row["bottom_temp_merged_c"]) and pd.isna(row["ctd_profile_id"])


def test_local_time_is_read_as_atlantic_daylight_time():
    # 15:45 UTC is 15 min after the tow ends under UTC-3; under UTC-4 it would be 45 min before it started.
    assert merged(tows(), casts(("C", "2016-07-01 15:45", 44.025, -63.0, 6.5)))["ctd_profile_id"] == "C"
    assert pd.isna(merged(tows(), casts(("C", "2016-07-01 12:45", 44.025, -63.0, 6.5)))["ctd_profile_id"])


def test_cast_named_for_the_tow_wins_and_may_be_further_away():
    table = casts(
        ("CTD_OTHER_009_1_DN", "2016-07-01 15:40", 44.021, -63.0, 9.0),      # closest, filed under another cruise
        ("CTD_NED2016016_005_2_DN", "2016-07-01 13:00", 44.0, -63.0, 6.0),  # named for this tow, 2.2 km, before it
    )
    row = merged(tows(), table)
    assert (row["ctd_profile_id"], row["ctd_match"], row["bottom_temp_merged_c"]) == ("CTD_NED2016016_005_2_DN", "id", 6.0)


def test_cast_named_for_another_tow_of_the_same_mission_is_never_borrowed():
    neighbour = casts(("CTD_NED2016016_004_1_DN", "2016-07-01 15:45", 44.025, -63.0, 6.5))
    assert pd.isna(merged(tows(), neighbour)["ctd_profile_id"])


def test_mislabelled_far_away_cast_is_not_matched_by_id():
    far = casts(("CTD_NED2016016_005_1_DN", "2016-07-01 15:45", 46.0, -63.0, 6.5))  # 220 km away
    assert pd.isna(merged(tows(), far)["ctd_profile_id"])


def test_no_casts_at_all():
    row = merged(tows(bottom_temp_c=5.0), casts())
    assert (row["bottom_temp_merged_c"], row["bottom_temp_source"]) == (5.0, "survey")
    assert pd.isna(row["ctd_profile_id"])
