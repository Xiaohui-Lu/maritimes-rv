import pandas as pd

from maritimes_rv import qc

STRATA = pd.DataFrame({
    "stratum": pd.array(["461"], dtype="string"),
    "depth_min_fm": pd.array([101], dtype="Int16"),
    "depth_max_fm": pd.array([200], dtype="Int16"),
})


def sets(n=1, **columns):
    """n ordinary tows; keyword arguments override columns with a scalar or a list of length n."""
    base = {
        "mission": "NED2000001", "setno": list(range(1, n + 1)), "year": 2000, "vessel_code": "N",
        "start_datetime_local": pd.Timestamp("2000-07-01 12:00"), "start_lat": 44.0, "start_lon": -63.0,
        "stratum": "461", "duration_min": 30, "distance_nmi": 1.75, "speed_kn": 3.5, "depth_m": 150 * 1.8288,
    }
    frame = pd.DataFrame(base | columns, index=range(n))
    return frame.astype({
        "stratum": "string", "duration_min": "Int16", "year": "Int16", "vessel_code": "string",
        "start_lat": "Float64", "start_lon": "Float64",
        "distance_nmi": "Float64", "speed_kn": "Float64", "depth_m": "Float64",
    })


def test_normal_tow_raises_no_flags():
    flagged = qc.flag_sets(sets(), STRATA)
    assert not flagged[["qc_speed_inconsistent", "qc_speed_implausible", "qc_depth_outside_stratum"]].any().any()


def test_recorded_speed_far_from_distance_over_duration_is_inconsistent():
    flagged = qc.flag_sets(sets(speed_kn=[36.0]), STRATA)  # NED1997726 set 21: 1.72 nmi in 30 min
    assert flagged.loc[0, "qc_speed_inconsistent"]
    assert not flagged.loc[0, "qc_speed_implausible"]


def test_consistent_but_too_fast_tow_is_implausible():
    flagged = qc.flag_sets(sets(duration_min=[21], distance_nmi=[2.5], speed_kn=[7.1]), STRATA)  # ATC1973212 set 27
    assert not flagged.loc[0, "qc_speed_inconsistent"]
    assert flagged.loc[0, "qc_speed_implausible"]


def test_depth_is_compared_in_fathoms_with_tolerance():
    inside_tolerance = 95 * 1.8288  # 6 fm shallower than the 101 fm band edge
    outside_tolerance = 85 * 1.8288  # 16 fm shallower
    flagged = qc.flag_sets(sets(2, depth_m=[inside_tolerance, outside_tolerance]), STRATA)
    assert flagged["qc_depth_outside_stratum"].tolist() == [False, True]


def test_second_vessel_fishing_beside_main_vessel_is_comparative():
    # Main vessel N: 3 tows. Teleost (S) mission: 2 tows on N's stations (~0.6 nmi away) a week later.
    tows = sets(
        5,
        mission=["NED2005001"] * 3 + ["TEL2005002"] * 2,
        vessel_code=["N", "N", "N", "S", "S"],
        start_lat=[44.0, 44.5, 45.0, 44.01, 44.51],
        start_datetime_local=pd.to_datetime(["2005-07-01 06:00", "2005-07-02 06:00", "2005-07-03 06:00",
                                             "2005-07-08 09:00", "2005-07-09 10:00"]),
    )
    assert qc.flag_sets(tows, STRATA)["qc_comparative_fishing"].tolist() == [False, False, False, True, True]


def test_second_vessel_covering_other_strata_is_not_comparative():
    # 1991-style split survey: the second vessel works far away, days later.
    tows = sets(
        4,
        mission=["HAM1991001"] * 2 + ["NED1991002"] * 2,
        vessel_code=["H", "H", "N", "N"],
        start_lat=[42.5, 42.6, 45.5, 45.6],
        start_datetime_local=pd.to_datetime(["1991-07-01", "1991-07-02", "1991-07-20", "1991-07-21"]),
    )
    tows.loc[2:, "setno"] = [3, 4]
    assert not qc.flag_sets(tows, STRATA)["qc_comparative_fishing"].any()


def test_missing_values_are_not_flagged():
    flagged = qc.flag_sets(sets(speed_kn=[None], depth_m=[None]), STRATA)
    assert not flagged[["qc_speed_inconsistent", "qc_depth_outside_stratum"]].any().any()


def test_zero_weight_is_flagged():
    catch = pd.DataFrame({"weight_kg_std": pd.array([0.0, 1.2, None], dtype="Float64")})
    assert qc.flag_catch(catch)["qc_weight_zero"].tolist() == [True, False, False]


def valid_tables():
    return {
        "missions": pd.DataFrame({"mission": ["NED2016016"], "vessel_code": ["N"]}).astype("string"),
        "sets": pd.DataFrame({"mission": ["NED2016016"], "setno": [1], "stratum": ["461"]}),
        "catch": pd.DataFrame({"mission": ["NED2016016"], "setno": [1], "species_code": [10]}),
        "species": pd.DataFrame({"species_code": [10]}),
        "strata": pd.DataFrame({"stratum": ["461"]}),
    }


def test_validate_accepts_consistent_tables():
    assert qc.validate(valid_tables()) == []


def test_validate_reports_duplicates_orphans_and_vessel_mismatch():
    tables = valid_tables()
    tables["sets"] = pd.concat([tables["sets"]] * 2)
    tables["catch"].loc[0, "species_code"] = 99
    tables["missions"].loc[0, "vessel_code"] = "S"
    problems = qc.validate(tables)
    assert any("duplicate primary keys" in p for p in problems)
    assert any("no match in species" in p for p in problems)
    assert any("does not match MISSION prefix" in p for p in problems)
