import pandas as pd
import pytest

from maritimes_rv import clean


def raw_inf(**overrides):
    row = {
        "MISSION": "NED2016016", "SETNO": 1, "SDATE": "2016-06-28", "TIME": 645, "STRAT": "461",
        "SLAT": 43.69, "SLONG": -62.99, "ELAT": None, "ELONG": None, "DUR": 30, "DIST": 1.75,
        "SPEED": 3.5, "DEPTH": 182.88, "SURF_TEMP": 14.0, "BOTT_TEMP": 6.0, "BOTT_SAL": 33.0,
        "GEARDESC": "Western IIA trawl",
    }
    return pd.DataFrame([row | overrides]).astype({"STRAT": "string"})


MISSIONS = pd.DataFrame({"mission": ["NED2016016"], "vessel_code": ["N"]})


def test_sets_builds_local_start_time_from_hhmm():
    sets = clean.clean_sets(pd.concat([raw_inf(TIME=645), raw_inf(SETNO=2, TIME=0)]), MISSIONS)
    assert list(sets["start_datetime_local"]) == [pd.Timestamp("2016-06-28 06:45"), pd.Timestamp("2016-06-28 00:00")]
    assert sets["year"].tolist() == [2016, 2016]


def test_sets_rejects_invalid_time():
    with pytest.raises(ValueError, match="HHMM"):
        clean.clean_sets(raw_inf(TIME=1275), MISSIONS)


def test_sets_keeps_stratum_as_text_and_copies_vessel():
    sets = clean.clean_sets(raw_inf(STRAT="5Z1"), MISSIONS)
    assert sets.loc[0, "stratum"] == "5Z1"
    assert sets.loc[0, "vessel_code"] == "N"


def test_catch_zero_count_becomes_missing_but_zero_weight_is_kept():
    raw = pd.DataFrame({
        "MISSION": ["M", "M"], "SETNO": [1, 1], "SPEC": [8600.0, 10.0],
        "TOTWGT": [2.5, 0.0], "TOTNO": [0.0, 1.0],
    })
    catch = clean.clean_catch(raw)
    assert pd.isna(catch.loc[0, "count_std"])  # sponges weighed but not counted
    assert catch.loc[1, "weight_kg_std"] == 0  # one fish below weighing precision
    assert catch.loc[1, "count_std"] == 1


def test_catch_drops_empty_placeholder_rows_only():
    raw = pd.DataFrame({
        "MISSION": ["M", "M"], "SETNO": [1, 2], "SPEC": [None, 10.0],
        "TOTWGT": [None, 1.0], "TOTNO": [None, 1.0],
    })
    catch = clean.clean_catch(raw)
    assert catch["setno"].tolist() == [2]
    assert catch["species_code"].dtype == "Int32"


def test_catch_rejects_values_without_species():
    raw = pd.DataFrame({"MISSION": ["M"], "SETNO": [1], "SPEC": [None], "TOTWGT": [1.0], "TOTNO": [None]})
    with pytest.raises(ValueError, match="no species code"):
        clean.clean_catch(raw)


def test_species_without_scientific_name_is_not_a_taxon():
    raw = pd.DataFrame({"CODE": [10, 9400], "SCI_NAME": ["GADUS MORHUA", None], "COMM": ["COD", "GARBAGE"]})
    assert clean.clean_species(raw)["is_taxon"].tolist() == [True, False]


def test_strata_core_flag_area_groups_and_km2():
    raw = pd.DataFrame({
        "STRAT": ["440", "466", "470", "495", "496", "5Z1"],
        "DMIN": [101, 101, 51, 0, 200, 51], "DMAX": [200, 200, 100, 49, 400, 100],
        "AREA": [1.0] * 6, "DEPTH": [0] * 6,
    })
    strata = clean.clean_strata(raw)
    assert strata["is_core"].tolist() == [True, True, True, True, False, False]
    assert strata["area_group"].tolist() == ["4VW", "4VW", "4X5Y", "4X5Y", pd.NA, pd.NA]
    assert strata.loc[0, "area_km2"] == pytest.approx(3.429904)
    assert "DEPTH" not in strata.columns


def test_missions_get_vessel_names_from_reference_table():
    raw = pd.DataFrame({"MISSION": ["TEL2022010"], "VESEL": ["S"], "CRUNO": [10], "YEAR": [2022], "SEASON": ["SUMMER"]})
    missions = clean.clean_missions(raw)
    assert missions.loc[0, "vessel_name"] == "CCGS Teleost"
    assert list(missions.columns) == ["mission", "year", "season", "vessel_code", "vessel_name", "cruise_no"]
