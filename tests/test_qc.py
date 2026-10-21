import pandas as pd

from maritimes_rv import qc

STRATA = pd.DataFrame({
    "stratum": pd.array(["461"], dtype="string"),
    "depth_min_fm": pd.array([101], dtype="Int16"),
    "depth_max_fm": pd.array([200], dtype="Int16"),
})


def sets(**columns):
    base = {
        "mission": ["M"], "setno": [1], "stratum": ["461"],
        "duration_min": [30], "distance_nmi": [1.75], "speed_kn": [3.5], "depth_m": [150 * 1.8288],
    }
    frame = pd.DataFrame(base | columns)
    return frame.astype({
        "stratum": "string", "duration_min": "Int16",
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
    flagged = qc.flag_sets(sets(setno=[1, 2], mission=["M", "M"], stratum=["461", "461"],
                                duration_min=[30, 30], distance_nmi=[1.75, 1.75], speed_kn=[3.5, 3.5],
                                depth_m=[inside_tolerance, outside_tolerance]), STRATA)
    assert flagged["qc_depth_outside_stratum"].tolist() == [False, True]


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
