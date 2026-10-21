"""Fill missing bottom temperatures from the CTD cast made at the same station.

On the summer survey a CTD is cast where each tow ends, shortly after it ends: a median of 0.8 km
from the tow's end position and 15 minutes later. A tow is matched to a cast in two ways:

1. by id: the profile id names the tow's mission and set number (CTD_NED2016016_249_...), and the
   cast lies within 10 km and 12 hours of the tow's end (a few ids are mislabelled);
2. by position: otherwise, the nearest cast within 2 km and 2 hours of the tow's end. This finds
   casts filed under another cruise number, as in 2005 and 2023.

Each way reproduces the survey's own bottom temperature to within 0.1 C for about 99% of the tows
that have both (docs/data_notes.md 3.14). Casts from other times or places disagree by degrees and
are never used to fill a gap.
"""
import numpy as np
import pandas as pd

MAX_DISTANCE_KM = 2.0
MAX_GAP_HOURS = 2.0
ID_MAX_DISTANCE_KM = 10.0
ID_MAX_GAP_HOURS = 12.0
ID_PATTERN = r"^CTD_([A-Z]{3}\d{7}|\d+)_(\d+)_"
# The survey's local time is Atlantic Daylight Time: casts at the tow's end position only line up in
# time with the end of the tow under UTC-3 (docs/data_notes.md 3.14).
LOCAL_TO_UTC = pd.Timedelta(hours=3)
MISMATCH_C = 0.5
BAD_FLAGS = [2, 3, 4, 9]  # BIO quality flags: inconsistent, doubtful, erroneous, missing


def distance_km(lat1, lon1, lat2, lon2):
    p1, p2 = np.radians(lat1), np.radians(lat2)
    a = np.sin((p2 - p1) / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(np.radians(lon2 - lon1) / 2) ** 2
    return 6371 * 2 * np.arcsin(np.sqrt(a))


def match_ctd(sets: pd.DataFrame, ctd: pd.DataFrame) -> pd.DataFrame:
    """For each tow with a same-station cast: that cast, how it was matched, its distance and temperature."""
    columns = ["row", "ctd_profile_id", "ctd_match", "ctd_distance_km", "ctd_bottom_temp_c"]
    usable = ctd[ctd["bottom_temp_c"].notna() & ~ctd["temp_flag"].isin(BAD_FLAGS).fillna(False)]
    if usable.empty:
        return pd.DataFrame(columns=columns)
    named = usable["profile_id"].str.extract(ID_PATTERN)
    named_mission = named[0].fillna("").astype(str).to_numpy()  # plain strings: NA cannot be compared elementwise
    named_set = pd.to_numeric(named[1], errors="coerce").to_numpy(dtype=float)
    mission = sets["mission"].astype(str).to_numpy()
    setno = sets["setno"].astype(float).to_numpy()
    lat = sets["end_lat"].fillna(sets["start_lat"]).astype(float).to_numpy()  # the end is where the cast is made
    lon = sets["end_lon"].fillna(sets["start_lon"]).astype(float).to_numpy()
    end = (sets["start_datetime_local"] + LOCAL_TO_UTC
           + pd.to_timedelta(sets["duration_min"].astype(float), unit="min")).to_numpy()
    years = sets["year"].astype(int).to_numpy()
    cast_years = usable["time_utc"].dt.year.to_numpy()

    matches = []
    for year in np.unique(years):
        tows = np.flatnonzero(years == year)
        in_year = np.flatnonzero(cast_years == year)
        if not len(in_year):
            continue
        casts = usable.iloc[in_year]
        km = distance_km(lat[tows, None], lon[tows, None],
                         casts["lat"].astype(float).to_numpy()[None, :], casts["lon"].astype(float).to_numpy()[None, :])
        hours = np.abs(casts["time_utc"].to_numpy()[None, :] - end[tows, None]) / np.timedelta64(1, "h")
        same_mission = named_mission[in_year][None, :] == mission[tows, None]
        is_named = same_mission & (named_set[in_year][None, :] == setno[tows, None])
        by_id = np.where(is_named & (km <= ID_MAX_DISTANCE_KM) & (hours <= ID_MAX_GAP_HOURS), km, np.inf)
        # A cast named for another tow of the same mission belongs to that tow, however close it is
        named_for_other = same_mission & ~is_named
        by_position = np.where((km <= MAX_DISTANCE_KM) & (hours <= MAX_GAP_HOURS) & ~named_for_other, km, np.inf)
        use_id = np.isfinite(by_id).any(axis=1)
        candidates = np.where(use_id[:, None], by_id, by_position)
        best = candidates.argmin(axis=1)
        found = np.isfinite(candidates[np.arange(len(tows)), best])
        matches.append(pd.DataFrame({
            "row": tows[found],
            "ctd_profile_id": casts["profile_id"].to_numpy()[best[found]],
            "ctd_match": np.where(use_id[found], "id", "position"),
            "ctd_distance_km": candidates[np.flatnonzero(found), best[found]],
            "ctd_bottom_temp_c": casts["bottom_temp_c"].astype(float).to_numpy()[best[found]],
        }))
    return pd.concat(matches, ignore_index=True) if matches else pd.DataFrame(columns=columns)


def add_ctd_temperature(sets: pd.DataFrame, ctd: pd.DataFrame) -> pd.DataFrame:
    """The survey's bottom temperature where it has one, else the same-station CTD cast's."""
    out = sets.reset_index(drop=True)
    found = match_ctd(out, ctd).set_index("row")
    out["ctd_profile_id"] = found["ctd_profile_id"].reindex(out.index).astype("string")
    out["ctd_match"] = found["ctd_match"].reindex(out.index).astype("string")
    out["ctd_distance_km"] = found["ctd_distance_km"].reindex(out.index).astype("Float64").round(3)
    out["ctd_bottom_temp_c"] = found["ctd_bottom_temp_c"].reindex(out.index).astype("Float64")
    survey = out["bottom_temp_c"]
    out["bottom_temp_merged_c"] = survey.fillna(out["ctd_bottom_temp_c"])
    source = pd.Series(pd.NA, index=out.index, dtype="string")
    source[survey.notna()] = "survey"
    source[survey.isna() & out["ctd_bottom_temp_c"].notna()] = "ctd"
    out["bottom_temp_source"] = source
    # Where both sources have a value they should agree; a large difference points to an error in one
    out["qc_ctd_temp_mismatch"] = ((survey - out["ctd_bottom_temp_c"]).abs() > MISMATCH_C).fillna(False)
    return out
