"""Package the cleaned tables and products as a downloadable data release.

A release is one zip (all tables as Parquet and CSV, a data dictionary, a README and the manifests)
plus files published beside it: sources.json, the fingerprint of the source data the release was
built from (the scheduled update check compares against it), SHA256SUMS and the release notes.
Facts in the README that depend on the data (year range, incomplete years) are computed from it,
so an automated release built from newer data never ships a stale description.
"""
import hashlib
import json
import zipfile
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

import pandas as pd

from . import fetch

CLEAN = ("missions", "sets", "catch", "species", "strata")
PRODUCTS = ("index", "bottom_temp")

# Every column of every released table; data_dictionary() fails if this drifts from the tables.
COLUMNS = {
    "missions": {
        "mission": "Survey trip identifier, e.g. NED2016016",
        "year": "Survey year",
        "season": "Survey season",
        "vessel_code": "One-letter vessel code",
        "vessel_name": "Vessel name, inferred from the mission prefix",
        "cruise_no": "Cruise number",
    },
    "sets": {
        "mission": "Survey trip identifier",
        "setno": "Tow number within the trip",
        "year": "Survey year",
        "start_datetime_local": "Tow start, local time (time zone not stated in the source)",
        "stratum": "Survey stratum code (text: some codes, such as 5Z1, are not numbers)",
        "start_lat": "Start latitude, decimal degrees",
        "start_lon": "Start longitude, decimal degrees",
        "end_lat": "End latitude, decimal degrees (missing before 1990)",
        "end_lon": "End longitude, decimal degrees (missing before 1990)",
        "duration_min": "Tow duration, minutes",
        "distance_nmi": "Tow distance, nautical miles",
        "speed_kn": "Recorded tow speed, knots",
        "depth_m": "Depth, metres",
        "surface_temp_c": "Surface temperature, degrees C",
        "bottom_temp_c": "Bottom temperature, degrees C",
        "bottom_salinity_psu": "Bottom salinity, practical salinity units",
        "gear": "Trawl used",
        "vessel_code": "One-letter vessel code (copied from missions)",
        "qc_speed_inconsistent": "Recorded speed differs from distance / duration by more than 1 knot",
        "qc_speed_implausible": "Distance / duration is outside 2-5 knots",
        "qc_depth_outside_stratum": "Depth is more than 10 fathoms outside the stratum's depth band",
        "qc_comparative_fishing": "Tow from a vessel-comparison experiment; excluded from the index",
    },
    "catch": {
        "mission": "Survey trip identifier",
        "setno": "Tow number within the trip",
        "species_code": "DFO Maritimes species code (see species)",
        "weight_kg_std": "Catch weight per standard 1.75 nmi tow, kg (already standardised by DFO)",
        "count_std": "Catch count per standard 1.75 nmi tow (fractional; missing when not counted)",
        "qc_weight_zero": "Weight recorded as 0 with a count; mostly below the weighing precision",
    },
    "species": {
        "species_code": "DFO Maritimes species code",
        "scientific_name": "Scientific name",
        "common_name": "English common name",
        "is_taxon": "False for non-biological codes such as stones, garbage or 'unidentified per set'",
    },
    "strata": {
        "stratum": "Survey stratum code",
        "depth_min_fm": "Minimum depth of the stratum, fathoms",
        "depth_max_fm": "Maximum depth of the stratum, fathoms",
        "area_nmi2": "Stratum area, square nautical miles",
        "area_km2": "Stratum area, square kilometres",
        "is_core": "True for the core strata 440-495",
        "area_group": "4VW (strata 440-466) or 4X5Y (470-495); empty outside the core strata",
    },
    "index": {
        "region": "core (strata 440-495), 4VW (440-466) or 4X5Y (470-495)",
        "year": "Survey year",
        "species_code": "DFO Maritimes species code",
        "n_sets": "Tows used in the region that year",
        "n_strata_sampled": "Strata with at least one tow",
        "n_strata_total": "Strata in the region",
        "area_coverage": "Area of the sampled strata / area of the region",
        "complete": "area_coverage >= 0.9; compare only complete years",
        "gears": "Trawl(s) used that year",
        "vessels": "Vessel code(s) used that year",
        "conversion_applied": "Vessel conversion factors were applied",
        "mean_count_per_tow": "Stratified mean count per standard tow",
        "se_count_per_tow": "Standard error of mean_count_per_tow",
        "mean_weight_kg_per_tow": "Stratified mean weight per standard tow, kg",
        "se_weight_kg_per_tow": "Standard error of mean_weight_kg_per_tow",
        "total_count": "Trawlable total count (relative index, not stock size)",
        "se_total_count": "Standard error of total_count",
        "total_weight_t": "Trawlable total weight, tonnes (relative index, not stock size)",
        "se_total_weight_t": "Standard error of total_weight_t",
        "n_count_missing": "Tows where the species was caught but not counted",
        "n_weight_missing": "Tows where the species was caught but not weighed",
    },
    "bottom_temp": {
        "region": "core (strata 440-495), 4VW (440-466) or 4X5Y (470-495)",
        "year": "Survey year",
        "n_sets_with_temp": "Tows with a bottom temperature reading",
        "n_strata_sampled": "Strata with at least one reading",
        "n_strata_total": "Strata in the region",
        "area_coverage": "Area of the strata with readings / area of the region",
        "complete": "area_coverage >= 0.9",
        "mean_bottom_temp_c": "Stratified mean bottom temperature, degrees C",
        "se_bottom_temp_c": "Standard error of mean_bottom_temp_c",
    },
}

ROW_LABELS = {
    "missions": "survey trip", "sets": "tow", "catch": "tow and species caught", "species": "species code",
    "strata": "stratum", "index": "region, year and species", "bottom_temp": "region and year",
}

README = """\
# Maritimes summer RV survey: cleaned tables and indices ({tag})

Analysis-ready tables built from the public release of the DFO Maritimes summer research vessel
bottom trawl survey (Scotian Shelf and Bay of Fundy, {first_year}-{last_year}) by maritimes-rv {package_version}.
Generated {generated}.

## Contents

{contents}

Every table is provided as Parquet (keeps column types) and CSV. `data_dictionary.csv` describes every
column. `clean/manifest.json` and `products/manifest.json` record the source checksums and parameters,
and `sources.json` fingerprints the source data this release was built from.

## Reading the data

- Python: `pandas.read_parquet("products/index.parquet")`
- R: `arrow::read_parquet("products/index.parquet")`
- SQL (DuckDB): `SELECT * FROM 'products/index.parquet' WHERE species_code = 11 AND region = '4X5Y'`

## Before you use it

- Catch weights and counts are per standard 1.75 nmi tow. DFO had already standardised them; do not
  rescale by tow distance again.
- `catch` lists only species that were caught. For any analysis, treat a missing tow-species pair as 0.
- `count_std` is missing where the catch was weighed but not counted (mostly invertebrates).
- In `index` and `bottom_temp`, compare only rows with `complete = true`. Incomplete survey coverage:
{incomplete_index}
- Bottom temperature, years without full coverage:
{incomplete_temp}
- Tows flagged `qc_comparative_fishing` repeat stations already fished and are excluded from `index`.
- Vessel conversion factors are {conversion}. Catchability differs across vessels and trawls, so long
  series may not be directly comparable.
- Totals assume the trawl catches every fish in its path; they are relative indices, not stock size.

## Source and licence

Contains information licensed under the Open Government Licence - Canada
(https://open.canada.ca/en/open-government-licence-canada).

Source: Fisheries and Oceans Canada, Maritimes Summer Research Vessel Survey,
https://open.canada.ca/data/en/dataset/1366e1f1-e2c8-4905-89ae-e10f1be0a164

This is an independent product; it is not produced or endorsed by Fisheries and Oceans Canada.
"""


def data_dictionary(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = []
    for name, table in tables.items():
        described = COLUMNS[name]
        undocumented = sorted(set(table.columns) - set(described))
        stale = sorted(set(described) - set(table.columns))
        if undocumented or stale:
            raise ValueError(f"{name}: columns without a description {undocumented}, "
                             f"descriptions without a column {stale}")
        rows += [{"table": name, "column": c, "type": str(table[c].dtype), "description": described[c]}
                 for c in table.columns]
    return pd.DataFrame(rows)


def _incomplete_years(table: pd.DataFrame) -> str:
    """One bullet per region listing its incomplete years, e.g. '  - 4VW: 2018, 2021, 2022'."""
    rows = table.loc[~table["complete"].astype(bool), ["region", "year"]].drop_duplicates()
    lines = [f"  - {region}: {', '.join(str(y) for y in sorted(years))}"
             for region, years in rows.groupby("region")["year"]]
    return "\n".join(lines) or "  - none"


def build_release(clean_dir: Path, products_dir: Path, raw_dir: Path, out_dir: Path, tag: str) -> list[Path]:
    """Write <out>/maritimes-rv-data-<tag>.zip, sources.json, SHA256SUMS and release_notes.md."""
    tables = {name: pd.read_parquet(clean_dir / f"{name}.parquet") for name in CLEAN}
    tables |= {name: pd.read_parquet(products_dir / f"{name}.parquet") for name in PRODUCTS}
    dictionary = data_dictionary(tables)
    sources = json.dumps(fetch.fingerprint(raw_dir), indent=2, sort_keys=True) + "\n"

    contents = "\n".join(
        ["| File | One row per | Rows |", "|---|---|---|"]
        + [f"| `{'clean' if name in CLEAN else 'products'}/{name}` | {ROW_LABELS[name]} | {len(t):,} |"
           for name, t in tables.items()]
    )
    years = tables["missions"]["year"]
    converted = bool(tables["index"]["conversion_applied"].any())
    readme = README.format(
        tag=tag, package_version=version("maritimes-rv"), contents=contents,
        generated=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        first_year=int(years.min()), last_year=int(years.max()),
        incomplete_index=_incomplete_years(tables["index"]),
        incomplete_temp=_incomplete_years(tables["bottom_temp"]),
        conversion="applied (Fanning 1985, haddock and four flatfish)" if converted else "not applied",
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    root = f"maritimes-rv-data-{tag}"
    archive = out_dir / f"{root}.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"{root}/README.md", readme)
        z.writestr(f"{root}/data_dictionary.csv", dictionary.to_csv(index=False))
        z.writestr(f"{root}/sources.json", sources)
        for subdir, source_dir, names in (("clean", clean_dir, CLEAN), ("products", products_dir, PRODUCTS)):
            for name in names:
                for suffix in (".parquet", ".csv"):
                    z.write(source_dir / f"{name}{suffix}", f"{root}/{subdir}/{name}{suffix}")
            z.write(source_dir / "manifest.json", f"{root}/{subdir}/manifest.json")

    # Always LF line endings: the update check compares sources.json byte for byte, on Linux runners.
    sources_file = out_dir / "sources.json"
    sources_file.write_text(sources, encoding="utf-8", newline="\n")
    checksums = out_dir / "SHA256SUMS"
    checksums.write_text("".join(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n"
                                 for p in (archive, sources_file)), encoding="utf-8", newline="\n")
    notes = out_dir / "release_notes.md"
    notes.write_text(
        f"Cleaned tables and stratified indices built by maritimes-rv {version('maritimes-rv')} "
        f"from the DFO Maritimes summer RV survey open data ({int(years.min())}-{int(years.max())}).\n\n"
        f"{contents}\n\nSee README.md in the zip for how to read the data and what to watch for. "
        "Contains information licensed under the Open Government Licence - Canada.\n",
        encoding="utf-8", newline="\n",
    )
    return [archive, sources_file, checksums, notes]
