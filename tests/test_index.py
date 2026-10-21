"""Stratified index tests. Expected values are worked out by hand in the comments."""
import math

import pandas as pd
import pytest

from maritimes_rv import index

# Three strata: 440 and 441 form region 4VW, 470 forms 4X5Y; all three are "core".
STRATA = pd.DataFrame({
    "stratum": pd.array(["440", "441", "470"], dtype="string"),
    "area_nmi2": pd.array([100.0, 300.0, 300.0], dtype="Float64"),
    "is_core": pd.array([True, True, True], dtype="boolean"),
    "area_group": pd.array(["4VW", "4VW", "4X5Y"], dtype="string"),
})
SPECIES = pd.DataFrame({"species_code": pd.array([11, 9400], dtype="Int32"),
                        "is_taxon": pd.array([True, False], dtype="boolean")})


def make_sets(rows):
    """rows: (setno, year, stratum, vessel_code, bottom_temp_c)."""
    frame = pd.DataFrame(rows, columns=["setno", "year", "stratum", "vessel_code", "bottom_temp_c"])
    frame.insert(0, "mission", "M")
    frame["gear"] = "Western IIA trawl"
    frame["qc_comparative_fishing"] = False
    frame = frame.astype({"setno": "Int16", "year": "Int16", "stratum": "string", "vessel_code": "string",
                          "bottom_temp_c": "Float64", "gear": "string", "qc_comparative_fishing": "boolean"})
    frame["bottom_temp_merged_c"] = frame["bottom_temp_c"]
    frame["bottom_temp_source"] = pd.Series(pd.NA, index=frame.index, dtype="string").mask(frame["bottom_temp_c"].notna(), "survey")
    return frame


def make_catch(rows):
    """rows: (setno, species_code, count_std, weight_kg_std)."""
    frame = pd.DataFrame(rows, columns=["setno", "species_code", "count_std", "weight_kg_std"])
    frame.insert(0, "mission", "M")
    return frame.astype({"setno": "Int16", "species_code": "Int32", "count_std": "Float64", "weight_kg_std": "Float64"})


# Year 2000: stratum 440 has three tows with haddock counts 0 (not caught), 2, 4; stratum 470 has 6, 6.
# Year 2001: stratum 440 again 0, 2, 4; stratum 441 has a single tow with 10; 470 is not sampled.
SETS = make_sets([
    (1, 2000, "440", "N", 5.0), (2, 2000, "440", "N", 7.0), (3, 2000, "440", "N", None),
    (4, 2000, "470", "N", 9.0), (5, 2000, "470", "N", 9.0),
    (6, 2001, "440", "N", None), (7, 2001, "440", "N", None), (8, 2001, "440", "N", None),
    (9, 2001, "441", "N", None),
])
CATCH = make_catch([
    (2, 11, 2, 1.0), (3, 11, 4, 2.0), (4, 11, 6, 3.0), (5, 11, 6, 3.0),
    (7, 11, 2, 1.0), (8, 11, 4, 2.0), (9, 11, 10, 5.0),
])


@pytest.fixture(scope="module")
def result():
    return index.build_index(SETS, CATCH, SPECIES, STRATA).set_index(["region", "year"])


def test_zero_fill_separates_not_caught_from_not_measured():
    catch = make_catch([(2, 11, None, 1.0)])
    filled = index.zero_fill(SETS[SETS["year"] == 2000], catch, 11).set_index("setno")
    assert filled.loc[1, "count_std"] == 0  # not caught
    assert pd.isna(filled.loc[2, "count_std"])  # caught, weighed, not counted
    assert filled.loc[2, "weight_kg_std"] == 1.0


def test_stratified_mean_and_se(result):
    row = result.loc[("core", 2000)]
    # stratum means: 440 -> 2, 470 -> 6; mean = (100*2 + 300*6) / 400 = 5
    assert row["mean_count_per_tow"] == pytest.approx(5.0)
    # se_440 = sd(0,2,4)/sqrt(3) = 2/sqrt(3); se_470 = 0; SE = sqrt(100^2 * 4/3) / 400
    assert row["se_count_per_tow"] == pytest.approx(math.sqrt(100**2 * 4 / 3) / 400)
    assert row["mean_weight_kg_per_tow"] == pytest.approx((100 * 1.0 + 300 * 3.0) / 400)


def test_single_tow_stratum_is_left_out_of_se_and_weights_renormalised(result):
    row = result.loc[("4VW", 2001)]
    # mean uses both strata: (100*2 + 300*10) / 400 = 8
    assert row["mean_count_per_tow"] == pytest.approx(8.0)
    # SE only from stratum 440 (441 has one tow), weights renormalised to 440's area: se_440 itself
    assert row["se_count_per_tow"] == pytest.approx(2 / math.sqrt(3))


def test_totals_expand_by_trawlable_units(result):
    # one standard tow sweeps 1.75 nmi x 41 ft = 1.75 * 41 * 0.3048 / 1852 nmi^2
    assert index.SWEPT_AREA_NMI2 == pytest.approx(0.011808531, rel=1e-6)
    row = result.loc[("4X5Y", 2000)]
    assert row["total_count"] == pytest.approx(300 / index.SWEPT_AREA_NMI2 * 6)
    assert row["total_weight_t"] == pytest.approx(300 / index.SWEPT_AREA_NMI2 * 3 / 1000)
    assert row["se_total_count"] == 0  # both tows caught 6


def test_coverage_flags_incomplete_and_keeps_years_without_tows(result):
    core = result.loc[("core", 2000)]
    assert (core["n_strata_sampled"], core["n_strata_total"]) == (2, 3)
    assert core["area_coverage"] == pytest.approx(400 / 700, abs=1e-4)
    assert not core["complete"]
    assert result.loc[("4X5Y", 2000), "complete"]

    empty = result.loc[("4X5Y", 2001)]  # no tows in 470 that year: row kept, values missing
    assert empty["n_sets"] == 0 and not empty["complete"]
    assert pd.isna(empty["mean_count_per_tow"])


def test_only_taxa_by_default(result):
    assert set(result["species_code"]) == {11}


def test_comparative_fishing_tows_are_left_out():
    sets = SETS.copy()
    extra = make_sets([(10, 2000, "470", "S", 20.0)]).assign(qc_comparative_fishing=True)
    catch = pd.concat([CATCH, make_catch([(10, 11, 600, 300.0)])])
    out = index.build_index(pd.concat([sets, extra]), catch, SPECIES, STRATA).set_index(["region", "year"])
    assert out.loc[("4X5Y", 2000), "mean_count_per_tow"] == pytest.approx(6.0)  # the paired tow's 600 is ignored
    assert out.loc[("4X5Y", 2000), "n_sets"] == 2
    temp = index.build_bottom_temperature(pd.concat([sets, extra]), STRATA).set_index(["region", "year"])
    assert temp.loc[("4X5Y", 2000), "mean_bottom_temp_c"] == pytest.approx(9.0)


def test_missing_count_is_excluded_not_zero():
    catch = make_catch([(4, 11, None, 3.0), (5, 11, 6, 3.0)])
    row = index.build_index(SETS, catch, SPECIES, STRATA, [11]).set_index(["region", "year"]).loc[("4X5Y", 2000)]
    assert row["mean_count_per_tow"] == pytest.approx(6.0)  # mean of the one counted tow, not (0 + 6) / 2
    assert row["n_count_missing"] == 1
    assert row["n_weight_missing"] == 0


def test_conversion_applies_only_to_listed_species_and_vessels():
    sets = make_sets([(1, 1975, "470", "A", None), (2, 1990, "470", "N", None), (3, 1982, "470", "H", None)])
    catch = make_catch([(1, 11, 10, 5.0), (1, 10, 10, 5.0), (2, 11, 10, 5.0), (3, 40, 10, 5.0)])
    converted = index.apply_conversion(catch, sets, index.load_conversion_factors())
    assert converted["count_std"].tolist() == pytest.approx([12.0, 10.0, 10.0, 8.0])  # haddock x1.2 on A only; plaice x0.8 on H
    assert converted["weight_kg_std"].tolist() == pytest.approx([6.0, 5.0, 5.0, 4.0])


def test_conversion_flag_in_index():
    sets = make_sets([(1, 1975, "470", "A", None), (2, 1975, "470", "A", None), (3, 1990, "470", "N", None),
                      (4, 1990, "470", "N", None)])
    catch = make_catch([(1, 11, 10, 5.0), (3, 11, 10, 5.0)])
    out = index.build_index(sets, catch, SPECIES, STRATA, [11], convert=True).set_index(["region", "year"])
    assert out.loc[("4X5Y", 1975), "conversion_applied"]
    assert out.loc[("4X5Y", 1975), "mean_count_per_tow"] == pytest.approx(6.0)  # (12 + 0) / 2
    assert not out.loc[("4X5Y", 1990), "conversion_applied"]


def test_bottom_temperature_uses_only_tows_with_a_reading():
    temp = index.build_bottom_temperature(SETS, STRATA).set_index(["region", "year"])
    row = temp.loc[("core", 2000)]
    # 440: mean(5, 7) = 6, se = sd(5,7)/sqrt(2) = 1; 470: mean 9, se 0
    assert row["mean_bottom_temp_c"] == pytest.approx((100 * 6 + 300 * 9) / 400)
    assert row["se_bottom_temp_c"] == pytest.approx(math.sqrt(100**2 * 1) / 400)
    assert row["n_sets_with_temp"] == 4
    none = temp.loc[("core", 2001)]  # no readings that year
    assert none["n_sets_with_temp"] == 0 and not none["complete"]
    assert pd.isna(none["mean_bottom_temp_c"])


def test_bottom_temperature_counts_readings_filled_from_ctd():
    sets = SETS.copy()
    sets.loc[sets["setno"] == 3, ["bottom_temp_merged_c", "bottom_temp_source"]] = [6.0, "ctd"]  # 440: 5, 7, 6
    row = index.build_bottom_temperature(sets, STRATA).set_index(["region", "year"]).loc[("core", 2000)]
    assert row["n_sets_with_temp"] == 5 and row["n_from_ctd"] == 1
    assert row["mean_bottom_temp_c"] == pytest.approx((100 * 6 + 300 * 9) / 400)
