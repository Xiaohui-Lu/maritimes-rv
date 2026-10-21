"""Quality checks.

Two kinds, kept apart on purpose:
- flags (qc_* columns): a record looks suspicious, but users decide whether to exclude it;
- validate(): broken keys or references mean the tables cannot be trusted, so the build stops.

A flag is False when the values it needs are missing: no evidence of a problem is not a problem.
Thresholds were chosen from the data distributions; see docs/data_model.md section 3.2.
"""
import numpy as np
import pandas as pd

from .clean import FATHOM_M, load_vessels

SPEED_MISMATCH_KN = 1.0
SPEED_RANGE_KN = (2.0, 5.0)
DEPTH_TOLERANCE_FM = 10
PAIRED_DISTANCE_NMI = 3
PAIRED_MISSION_SHARE = 0.5

PRIMARY_KEYS = {
    "missions": ["mission"],
    "sets": ["mission", "setno"],
    "catch": ["mission", "setno", "species_code"],
    "species": ["species_code"],
    "strata": ["stratum"],
    "ctd": ["profile_id"],
}
FOREIGN_KEYS = [  # (child table, child columns, parent table, parent columns); a missing child value refers to nothing
    ("sets", ["mission"], "missions", ["mission"]),
    ("sets", ["stratum"], "strata", ["stratum"]),
    ("sets", ["ctd_profile_id"], "ctd", ["profile_id"]),
    ("catch", ["mission", "setno"], "sets", ["mission", "setno"]),
    ("catch", ["species_code"], "species", ["species_code"]),
]


def flag_sets(sets: pd.DataFrame, strata: pd.DataFrame) -> pd.DataFrame:
    out = sets.copy()
    tow_speed = out["distance_nmi"] / (out["duration_min"] / 60)
    # Recorded speed is normally DIST / DUR to within 0.05 kn, so a large gap means one of them is wrong.
    out["qc_speed_inconsistent"] = ((out["speed_kn"] - tow_speed).abs() > SPEED_MISMATCH_KN).fillna(False)
    # Standard tows run at about 3.5 kn. Catches are standardised by distance, so a wrong DIST
    # makes the standardised catch wrong too.
    out["qc_speed_implausible"] = (~tow_speed.between(*SPEED_RANGE_KN)).fillna(False)

    bands = strata.set_index("stratum")
    depth_fm = out["depth_m"] / FATHOM_M
    too_shallow = depth_fm < out["stratum"].map(bands["depth_min_fm"]) - DEPTH_TOLERANCE_FM
    too_deep = depth_fm > out["stratum"].map(bands["depth_max_fm"]) + DEPTH_TOLERANCE_FM
    out["qc_depth_outside_stratum"] = (too_shallow | too_deep).fillna(False)
    out["qc_comparative_fishing"] = _comparative_fishing(out)
    return out


def _comparative_fishing(sets: pd.DataFrame) -> pd.Series:
    """Tows from a second vessel fishing beside the main survey vessel (a vessel calibration experiment).

    They repeat stations the main vessel already fished, so the stratified index must leave them out.
    The open data has no tow-type column to mark them, so a mission is flagged when most of its tows
    start within 3 nmi of a tow by the year's main vessel. Time is not used: the second vessel came back
    to the stations 3-9 days later (2005 Teleost, 1981 Lady Hammond). A vessel sharing the survey works
    other strata instead (1991: nearest tows 21-224 nmi apart).
    """
    flagged = pd.Series(False, index=sets.index, dtype="boolean")
    for _, year in sets.groupby("year"):
        tows_per_vessel = year["vessel_code"].value_counts()
        if len(tows_per_vessel) < 2:
            continue
        main = year[year["vessel_code"] == tows_per_vessel.idxmax()]
        for _, mission in year[year["vessel_code"] != tows_per_vessel.idxmax()].groupby("mission"):
            lat = mission["start_lat"].to_numpy(float)[:, None]
            main_lat = main["start_lat"].to_numpy(float)[None, :]
            north_nmi = (lat - main_lat) * 60
            east_nmi = (mission["start_lon"].to_numpy(float)[:, None] - main["start_lon"].to_numpy(float)[None, :]) \
                * 60 * np.cos(np.radians((lat + main_lat) / 2))
            paired = (np.hypot(north_nmi, east_nmi) <= PAIRED_DISTANCE_NMI).any(axis=1)
            if paired.mean() >= PAIRED_MISSION_SHARE:
                flagged[mission.index] = True
    return flagged


def flag_catch(catch: pd.DataFrame) -> pd.DataFrame:
    out = catch.copy()
    # Weight 0 with a count: mostly below the 1 kg weighing precision used before 1990.
    out["qc_weight_zero"] = (out["weight_kg_std"] == 0).fillna(False)
    return out


def validate(tables: dict[str, pd.DataFrame]) -> list[str]:
    """Return a description of each integrity problem; an empty list means the tables are consistent."""
    problems = []
    for name, key in PRIMARY_KEYS.items():
        if name not in tables:
            continue
        table = tables[name]
        if table[key].isna().any().any():
            problems.append(f"{name}: missing values in primary key {key}")
        if (n := table.duplicated(key).sum()):
            problems.append(f"{name}: {n} duplicate primary keys {key}")

    for child, columns, parent, parent_columns in FOREIGN_KEYS:
        if child not in tables or parent not in tables or columns[0] not in tables[child]:
            continue
        known = pd.MultiIndex.from_frame(tables[parent][parent_columns].set_axis(columns, axis=1))
        references = tables[child][columns].dropna()
        orphans = ~pd.MultiIndex.from_frame(references).isin(known)
        if orphans.any():
            problems.append(f"{child}{columns}: {orphans.sum()} rows with no match in {parent}")

    # vessels.csv is inferred from MISSION prefixes; check the inference holds for every mission.
    prefixes = load_vessels().set_index("vessel_code")["mission_prefix"]
    missions = tables["missions"]
    mismatch = (missions["mission"].str[:3] != missions["vessel_code"].map(prefixes)).fillna(True)
    if mismatch.any():
        problems.append(f"missions: vessel code does not match MISSION prefix for {list(missions['mission'][mismatch])}")
    return problems
