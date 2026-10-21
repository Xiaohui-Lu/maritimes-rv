"""Turn raw tables into the cleaned tables defined in docs/data_model.md.

Cleaning renames columns, sets types and units, and applies the decisions in data_model.md section 1.
It never drops records for quality reasons; that is left to the qc_* flags.
"""
from importlib import resources

import pandas as pd

FATHOM_M = 1.8288
NMI2_TO_KM2 = 3.429904
CORE_STRATA = (440, 495)
AREA_GROUPS = {"4VW": (440, 466), "4X5Y": (470, 495)}


def load_vessels() -> pd.DataFrame:
    with resources.files("maritimes_rv").joinpath("reference/vessels.csv").open(encoding="utf-8") as f:
        return pd.read_csv(f, dtype="string")


def clean_missions(raw: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame({
        "mission": raw["MISSION"].astype("string"),
        "year": raw["YEAR"].astype("Int16"),
        "season": raw["SEASON"].astype("string"),
        "vessel_code": raw["VESEL"].astype("string"),
        "cruise_no": raw["CRUNO"].astype("Int16"),
    })
    names = load_vessels().set_index("vessel_code")["vessel_name"]
    out.insert(4, "vessel_name", out["vessel_code"].map(names).astype("string"))
    return out


def clean_sets(raw: pd.DataFrame, missions: pd.DataFrame) -> pd.DataFrame:
    date = pd.to_datetime(raw["SDATE"], format="%Y-%m-%d")
    time = raw["TIME"]  # local time as an HHMM integer, e.g. 645 = 06:45
    if ((time < 0) | (time > 2359) | (time % 100 >= 60)).any():
        raise ValueError("GSINF.TIME has values that are not valid HHMM times")
    start = date + pd.to_timedelta(time // 100, unit="h") + pd.to_timedelta(time % 100, unit="min")

    out = pd.DataFrame({
        "mission": raw["MISSION"].astype("string"),
        "setno": raw["SETNO"].astype("Int16"),
        "year": date.dt.year.astype("Int16"),
        "start_datetime_local": start,
        "stratum": raw["STRAT"].astype("string"),
        "start_lat": raw["SLAT"].astype("Float64"),
        "start_lon": raw["SLONG"].astype("Float64"),
        "end_lat": raw["ELAT"].astype("Float64"),
        "end_lon": raw["ELONG"].astype("Float64"),
        "duration_min": raw["DUR"].astype("Int16"),
        "distance_nmi": raw["DIST"].astype("Float64"),
        "speed_kn": raw["SPEED"].astype("Float64"),
        "depth_m": raw["DEPTH"].astype("Float64"),
        "surface_temp_c": raw["SURF_TEMP"].astype("Float64"),
        "bottom_temp_c": raw["BOTT_TEMP"].astype("Float64"),
        # The data dictionary says "pounds per square unit"; the values are practical salinity units.
        "bottom_salinity_psu": raw["BOTT_SAL"].astype("Float64"),
        "gear": raw["GEARDESC"].astype("string"),
    })
    out["vessel_code"] = out["mission"].map(missions.set_index("mission")["vessel_code"]).astype("string")
    return out


def clean_catch(raw: pd.DataFrame) -> pd.DataFrame:
    # Two source rows are entirely NA: placeholders for tows that caught nothing. Those tows are still
    # in `sets`, so zero-filling at analysis time gives them zeros without these rows.
    empty = raw["SPEC"].isna()
    if (empty & (raw["TOTWGT"].notna() | raw["TOTNO"].notna())).any():
        raise ValueError("GSCAT has rows with catch values but no species code")
    raw = raw[~empty]

    count = raw["TOTNO"].astype("Float64")
    return pd.DataFrame({
        "mission": raw["MISSION"].astype("string"),
        "setno": raw["SETNO"].astype("Int16"),
        "species_code": raw["SPEC"].astype("Int32"),
        # Both values are already standardised to a 1.75 nmi tow (data_notes.md 3.1): do not rescale.
        # A weight of 0 is kept: before 1990 weights were rounded to whole kg (data_notes.md 3.3).
        "weight_kg_std": raw["TOTWGT"].astype("Float64"),
        # A count of 0 always comes with a weight, so it means "not counted", not "none caught".
        "count_std": count.mask(count == 0),
    }).reset_index(drop=True)


def clean_species(raw: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame({
        "species_code": raw["CODE"].astype("Int32"),
        "scientific_name": raw["SCI_NAME"].astype("string"),
        "common_name": raw["COMM"].astype("string"),
    })
    # Codes without a scientific name are stones, garbage, "unidentified per set" and similar.
    out["is_taxon"] = out["scientific_name"].notna().astype("boolean")
    return out


def clean_strata(raw: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame({
        "stratum": raw["STRAT"].astype("string"),
        # Units are not documented; tow depths only fit the bands when read as fathoms (data_notes.md 3.4).
        "depth_min_fm": raw["DMIN"].astype("Int16"),
        "depth_max_fm": raw["DMAX"].astype("Int16"),
        "area_nmi2": raw["AREA"].astype("Float64"),
    })
    out["area_km2"] = out["area_nmi2"] * NMI2_TO_KM2

    number = pd.to_numeric(out["stratum"], errors="coerce")  # NA for codes such as 5Z1
    out["is_core"] = number.between(*CORE_STRATA).fillna(False).astype("boolean")
    group = pd.Series(pd.NA, index=out.index, dtype="string")
    for name, (low, high) in AREA_GROUPS.items():
        group[number.between(low, high).fillna(False)] = name
    out["area_group"] = group
    return out.sort_values("stratum", ignore_index=True)
