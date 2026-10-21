"""Stratified mean abundance and biomass indices, and stratified mean bottom temperature.

The formulas follow DFO Maritimes' RVTransmogrifier (stratify_simple and calcYearSummary in
github.com/Maritimes/RVTransmogrifier). For stratum h with area A_h, n_h tows, mean y_h and
standard error se_h = s_h / sqrt(n_h):

    stratified mean = sum(A_h * y_h) / sum(A_h)                over strata sampled that year
    its SE          = sqrt(sum(A_h^2 * se_h^2)) / sum(A_h)    over strata with n_h >= 2 only

Strata with a single tow have no variance estimate, so they are left out of the SE and the SE
weights are renormalised over the remaining strata. That is what DFO's code does; see
docs/data_model.md section 4.2 for this and the places where this module deliberately differs.
"""
from importlib import resources

import numpy as np
import pandas as pd

STANDARD_TOW_NMI = 1.75
WINGSPREAD_FT = 41  # Western IIA; used for all years, as in Fanning (1985) and Mar.stratisfy
FT_PER_NMI = 1852 / 0.3048
SWEPT_AREA_NMI2 = STANDARD_TOW_NMI * WINGSPREAD_FT / FT_PER_NMI  # area covered by one standard tow
# Observed region-year coverage is either >= 0.99 or <= 0.55, so any cut-off in between gives the same answer.
COMPLETE_AREA_SHARE = 0.9

METRICS = {"count": "count_std", "weight": "weight_kg_std"}
SET_KEY = ["mission", "setno"]


def survey_tows(sets: pd.DataFrame) -> pd.DataFrame:
    """Tows that belong to the stratified random design: comparative-fishing tows repeat stations."""
    return sets[~sets["qc_comparative_fishing"]]


def region_strata(strata: pd.DataFrame) -> dict[str, list[str]]:
    in_group = strata["area_group"].fillna("")
    return {
        "core": strata.loc[strata["is_core"], "stratum"].tolist(),
        "4VW": strata.loc[in_group == "4VW", "stratum"].tolist(),
        "4X5Y": strata.loc[in_group == "4X5Y", "stratum"].tolist(),
    }


def load_conversion_factors() -> pd.DataFrame:
    path = resources.files("maritimes_rv").joinpath("reference/conversion_factors.csv")
    with path.open(encoding="utf-8") as f:
        return pd.read_csv(f)


def apply_conversion(catch: pd.DataFrame, sets: pd.DataFrame, factors: pd.DataFrame) -> pd.DataFrame:
    """Scale catches from older vessels to their Alfred Needler / Western IIA equivalent."""
    vessel = catch[SET_KEY].merge(sets[SET_KEY + ["vessel_code"]], on=SET_KEY, how="left")["vessel_code"].to_numpy()
    factor = np.ones(len(catch))
    for row in factors.itertuples():
        match = (catch["species_code"] == row.species_code).to_numpy() & np.isin(vessel, row.vessel_codes.split(";"))
        factor[match] = row.factor
    out = catch.copy()
    for column in METRICS.values():
        out[column] = out[column] * factor
    return out


def zero_fill(sets: pd.DataFrame, catch: pd.DataFrame, species_code: int) -> pd.DataFrame:
    """One row per tow for one species: 0 where it was not caught, NA where caught but not measured."""
    caught = catch.loc[catch["species_code"] == species_code, SET_KEY + list(METRICS.values())]
    out = sets[SET_KEY + ["year", "stratum"]].merge(
        caught.assign(_caught=True), on=SET_KEY, how="left", validate="one_to_one"
    )
    not_caught = out["_caught"].isna()
    for column in METRICS.values():
        out[column] = out[column].mask(not_caught, 0)
    return out.drop(columns="_caught").assign(species_code=species_code)


def stratum_stats(values: pd.DataFrame, columns: dict[str, str]) -> pd.DataFrame:
    """n, mean and standard error per year x stratum (and species, if present) for each metric."""
    keys = [k for k in ("species_code", "year", "stratum") if k in values.columns]
    groups = values.groupby(keys)
    parts = {"n_sets": groups.size()}
    for metric, column in columns.items():
        x = groups[column]
        n = x.count()
        parts[f"n_{metric}"] = n
        parts[f"mean_{metric}"] = x.mean().astype(float)
        parts[f"se_{metric}"] = x.std().astype(float) / np.sqrt(n)  # std is NaN when n == 1
    return pd.DataFrame(parts).reset_index()


def combine_strata(stats: pd.DataFrame, area_nmi2: pd.Series, metric: str) -> pd.DataFrame:
    """Area-weighted mean and SE across strata, plus totals expanded by trawlable units."""
    s = stats[stats[f"n_{metric}"] > 0].copy()
    s["area"] = s["stratum"].map(area_nmi2).astype(float)
    mean, se = s[f"mean_{metric}"], s[f"se_{metric}"]
    has_se = se.notna()
    units = s["area"] / SWEPT_AREA_NMI2  # number of standard tows that would cover the stratum
    s["_a_mean"] = s["area"] * mean
    s["_a_var"] = (s["area"] ** 2 * se**2).where(has_se, 0)
    s["_a_with_se"] = s["area"].where(has_se, 0)
    s["_u_mean"] = units * mean
    s["_u_var"] = (units**2 * se**2).where(has_se, 0)

    keys = [k for k in ("species_code", "year") if k in s.columns]
    g = s.groupby(keys)[["area", "_a_mean", "_a_var", "_a_with_se", "_u_mean", "_u_var"]].sum()
    no_se = g["_a_with_se"] == 0  # DFO reports 0 here; an unknown SE is more honest
    return pd.DataFrame({
        f"mean_{metric}": g["_a_mean"] / g["area"],
        f"se_{metric}": (np.sqrt(g["_a_var"]) / g["_a_with_se"]).mask(no_se),
        f"total_{metric}": g["_u_mean"],
        f"se_total_{metric}": np.sqrt(g["_u_var"]).mask(no_se),
    }).reset_index()


def coverage(sets: pd.DataFrame, strata: pd.DataFrame, years: list[int]) -> pd.DataFrame:
    """Which strata were sampled in each region and year, including years with no tows at all."""
    area = strata.set_index("stratum")["area_nmi2"].astype(float)
    rows = []
    for region, members in region_strata(strata).items():
        in_region = sets[sets["stratum"].isin(members)]
        by_year = dict(tuple(in_region.groupby("year")))
        for year in years:
            tows = by_year.get(year, in_region.iloc[0:0])
            sampled = tows["stratum"].unique()
            share = area[sampled].sum() / area[members].sum()
            rows.append({
                "region": region, "year": year, "n_sets": len(tows),
                "n_strata_sampled": len(sampled), "n_strata_total": len(members),
                "area_coverage": round(share, 4), "complete": share >= COMPLETE_AREA_SHARE,
                "gears": "; ".join(sorted(tows["gear"].dropna().unique())),
                "vessels": ";".join(sorted(tows["vessel_code"].dropna().unique())),
            })
    return pd.DataFrame(rows).astype({"year": "Int16", "complete": "boolean", "gears": "string", "vessels": "string"})


def build_index(sets, catch, species, strata, species_codes=None, convert=False) -> pd.DataFrame:
    """One row per region x year x species. Uses every taxon unless species_codes is given."""
    if species_codes is None:
        species_codes = species.loc[species["is_taxon"], "species_code"].tolist()
    sets = survey_tows(sets)
    if convert:
        factors = load_conversion_factors()
        catch = apply_conversion(catch, sets, factors)

    stats = pd.concat([stratum_stats(zero_fill(sets, catch, code), METRICS) for code in species_codes])
    years = sorted(sets["year"].unique())
    area = strata.set_index("stratum")["area_nmi2"]

    frames = []
    for region, members in region_strata(strata).items():
        in_region = stats[stats["stratum"].isin(members)]
        result = combine_strata(in_region, area, "count").merge(
            combine_strata(in_region, area, "weight"), on=["species_code", "year"], how="outer"
        )
        missing = in_region.assign(
            n_count_missing=in_region["n_sets"] - in_region["n_count"],
            n_weight_missing=in_region["n_sets"] - in_region["n_weight"],
        ).groupby(["species_code", "year"])[["n_count_missing", "n_weight_missing"]].sum().reset_index()
        frames.append(result.merge(missing, on=["species_code", "year"], how="outer").assign(region=region))
    results = pd.concat(frames)

    grid = coverage(sets, strata, years).merge(pd.DataFrame({"species_code": species_codes}), how="cross")
    index = grid.merge(results, on=["region", "year", "species_code"], how="left")

    index["conversion_applied"] = False
    if convert:
        for row in factors.itertuples():
            uses_vessel = index["vessels"].fillna("").str.split(";").apply(lambda v, f=row: bool(set(v) & set(f.vessel_codes.split(";"))))
            index.loc[(index["species_code"] == row.species_code) & uses_vessel, "conversion_applied"] = True

    return pd.DataFrame({
        "region": index["region"].astype("string"),
        "year": index["year"],
        "species_code": index["species_code"].astype("Int32"),
        "n_sets": index["n_sets"].astype("Int16"),
        "n_strata_sampled": index["n_strata_sampled"].astype("Int16"),
        "n_strata_total": index["n_strata_total"].astype("Int16"),
        "area_coverage": index["area_coverage"].astype("Float64"),
        "complete": index["complete"],
        "gears": index["gears"],
        "vessels": index["vessels"],
        "conversion_applied": index["conversion_applied"].astype("boolean"),
        "mean_count_per_tow": index["mean_count"].astype("Float64"),
        "se_count_per_tow": index["se_count"].astype("Float64"),
        "mean_weight_kg_per_tow": index["mean_weight"].astype("Float64"),
        "se_weight_kg_per_tow": index["se_weight"].astype("Float64"),
        "total_count": index["total_count"].astype("Float64"),
        "se_total_count": index["se_total_count"].astype("Float64"),
        "total_weight_t": (index["total_weight"] / 1000).astype("Float64"),
        "se_total_weight_t": (index["se_total_weight"] / 1000).astype("Float64"),
        "n_count_missing": index["n_count_missing"].astype("Int16"),
        "n_weight_missing": index["n_weight_missing"].astype("Int16"),
    }).sort_values(["region", "species_code", "year"], ignore_index=True)


def build_bottom_temperature(sets: pd.DataFrame, strata: pd.DataFrame) -> pd.DataFrame:
    """Stratified mean bottom temperature per region x year, from tows that recorded one."""
    sets = survey_tows(sets)
    measured = sets[sets["bottom_temp_c"].notna()]
    stats = stratum_stats(measured, {"temp": "bottom_temp_c"})
    area = strata.set_index("stratum")["area_nmi2"]
    years = sorted(sets["year"].unique())

    frames = []
    for region, members in region_strata(strata).items():
        result = combine_strata(stats[stats["stratum"].isin(members)], area, "temp")
        frames.append(result[["year", "mean_temp", "se_temp"]].assign(region=region))
    # Coverage counts only tows with a temperature, so 2021-2023 (none recorded) come out incomplete.
    table = coverage(measured, strata, years).merge(pd.concat(frames), on=["region", "year"], how="left")
    return pd.DataFrame({
        "region": table["region"].astype("string"),
        "year": table["year"],
        "n_sets_with_temp": table["n_sets"].astype("Int16"),
        "n_strata_sampled": table["n_strata_sampled"].astype("Int16"),
        "n_strata_total": table["n_strata_total"].astype("Int16"),
        "area_coverage": table["area_coverage"].astype("Float64"),
        "complete": table["complete"],
        "mean_bottom_temp_c": table["mean_temp"].astype("Float64"),
        "se_bottom_temp_c": table["se_temp"].astype("Float64"),
    }).sort_values(["region", "year"], ignore_index=True)
