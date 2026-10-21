"""Quality checks.

Two kinds, kept apart on purpose:
- flags (qc_* columns): a record looks suspicious, but users decide whether to exclude it;
- validate(): broken keys or references mean the tables cannot be trusted, so the build stops.

A flag is False when the values it needs are missing: no evidence of a problem is not a problem.
Thresholds were chosen from the data distributions; see docs/data_model.md section 3.2.
"""
import pandas as pd

from .clean import FATHOM_M, load_vessels

SPEED_MISMATCH_KN = 1.0
SPEED_RANGE_KN = (2.0, 5.0)
DEPTH_TOLERANCE_FM = 10

PRIMARY_KEYS = {
    "missions": ["mission"],
    "sets": ["mission", "setno"],
    "catch": ["mission", "setno", "species_code"],
    "species": ["species_code"],
    "strata": ["stratum"],
}
FOREIGN_KEYS = [  # (child table, columns, parent table)
    ("sets", ["mission"], "missions"),
    ("sets", ["stratum"], "strata"),
    ("catch", ["mission", "setno"], "sets"),
    ("catch", ["species_code"], "species"),
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
    return out


def flag_catch(catch: pd.DataFrame) -> pd.DataFrame:
    out = catch.copy()
    # Weight 0 with a count: mostly below the 1 kg weighing precision used before 1990.
    out["qc_weight_zero"] = (out["weight_kg_std"] == 0).fillna(False)
    return out


def validate(tables: dict[str, pd.DataFrame]) -> list[str]:
    """Return a description of each integrity problem; an empty list means the tables are consistent."""
    problems = []
    for name, key in PRIMARY_KEYS.items():
        table = tables[name]
        if table[key].isna().any().any():
            problems.append(f"{name}: missing values in primary key {key}")
        if (n := table.duplicated(key).sum()):
            problems.append(f"{name}: {n} duplicate primary keys {key}")

    for child, columns, parent in FOREIGN_KEYS:
        known = pd.MultiIndex.from_frame(tables[parent][columns])
        orphans = ~pd.MultiIndex.from_frame(tables[child][columns]).isin(known)
        if orphans.any():
            problems.append(f"{child}{columns}: {orphans.sum()} rows with no match in {parent}")

    # vessels.csv is inferred from MISSION prefixes; check the inference holds for every mission.
    prefixes = load_vessels().set_index("vessel_code")["mission_prefix"]
    missions = tables["missions"]
    mismatch = (missions["mission"].str[:3] != missions["vessel_code"].map(prefixes)).fillna(True)
    if mismatch.any():
        problems.append(f"missions: vessel code does not match MISSION prefix for {list(missions['mission'][mismatch])}")
    return problems
