"""Build the static website and its read-only JSON API from the cleaned tables and products.

The site is a view of one data release. Its data are JSON files at stable URLs:

    api/v1/meta.json           release, source checksums, regions, field descriptions
    api/v1/species.json        every taxon caught, most frequently caught first
    api/v1/index/<code>.json   yearly index series for one species, by region (columns of equal length)
    api/v1/bottom_temp.json    yearly bottom temperature, by region

and one page (site_assets/) that charts them. Static files need no server to keep running.
"""
import json
import os
import shutil
from datetime import datetime, timezone
from importlib import resources
from importlib.metadata import version
from pathlib import Path

import pandas as pd

from . import index as index_module
from .release import COLUMNS

API_DIR = "api/v1"
DEFAULT_REPOSITORY = "https://github.com/Xiaohui-Lu/maritimes-rv"
INDEX_FIELDS = [
    "n_sets", "n_strata_sampled", "n_strata_total", "area_coverage", "complete", "gears", "vessels",
    "mean_count_per_tow", "se_count_per_tow", "mean_weight_kg_per_tow", "se_weight_kg_per_tow",
    "total_count", "se_total_count", "total_weight_t", "se_total_weight_t",
]
TEMP_FIELDS = ["n_sets_with_temp", "n_from_ctd", "n_strata_sampled", "n_strata_total", "area_coverage", "complete",
               "mean_bottom_temp_c", "se_bottom_temp_c"]


def column(values: pd.Series) -> list:
    """A JSON-ready list: missing values become null (JSON has no NaN), floats keep 6 significant digits."""
    if pd.api.types.is_bool_dtype(values):
        return [None if pd.isna(v) else bool(v) for v in values]
    if pd.api.types.is_integer_dtype(values):
        return [None if pd.isna(v) else int(v) for v in values]
    if pd.api.types.is_float_dtype(values):
        return [None if pd.isna(v) else float(f"{v:.6g}") for v in values]
    return [None if pd.isna(v) else str(v) for v in values]


def by_region(table: pd.DataFrame, fields: list[str]) -> dict:
    # Fields a release built by an older version lacks are left out, so the site still builds from it
    present = [f for f in fields if f in table.columns]
    return {
        str(region): {"year": column(rows["year"]), **{f: column(rows[f]) for f in present}}
        for region, rows in table.sort_values("year").groupby("region", sort=True)
    }


def species_list(species: pd.DataFrame, catch: pd.DataFrame, sets: pd.DataFrame) -> pd.DataFrame:
    tows = index_module.survey_tows(sets)[["mission", "setno"]]
    caught = catch.merge(tows, on=["mission", "setno"]).groupby("species_code").size().rename("n_tows_caught")
    taxa = species[species["is_taxon"].astype(bool)].merge(caught, left_on="species_code", right_index=True)
    return taxa.sort_values(["n_tows_caught", "species_code"], ascending=[False, True], ignore_index=True)


def _write(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, separators=(",", ":"), allow_nan=False), encoding="utf-8", newline="\n")


def build_site(clean_dir: Path, products_dir: Path, out_dir: Path, tag: str,
               repository: str | None = None) -> dict[str, int]:
    """Write the page and the JSON API to out_dir (replacing it). Returns file counts by kind."""
    sets = pd.read_parquet(clean_dir / "sets.parquet")
    catch = pd.read_parquet(clean_dir / "catch.parquet")
    species = pd.read_parquet(clean_dir / "species.parquet")
    strata = pd.read_parquet(clean_dir / "strata.parquet")
    idx = pd.read_parquet(products_dir / "index.parquet")
    temp = pd.read_parquet(products_dir / "bottom_temp.parquet")
    missions = pd.read_parquet(clean_dir / "missions.parquet")
    clean_manifest = json.loads((clean_dir / "manifest.json").read_text(encoding="utf-8"))
    if repository is None and os.environ.get("GITHUB_REPOSITORY"):
        repository = f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/{os.environ['GITHUB_REPOSITORY']}"

    if out_dir.exists():
        shutil.rmtree(out_dir)
    for asset in resources.files("maritimes_rv").joinpath("site_assets").iterdir():
        (out_dir / asset.name).parent.mkdir(parents=True, exist_ok=True)
        (out_dir / asset.name).write_bytes(asset.read_bytes())
    api = out_dir / API_DIR

    listed = species_list(species, catch, sets)
    listed = listed[listed["species_code"].isin(idx["species_code"].unique())]
    _write(api / "species.json", [
        {"code": int(r.species_code), "scientific_name": r.scientific_name,
         "common_name": None if pd.isna(r.common_name) else r.common_name, "n_tows_caught": int(r.n_tows_caught)}
        for r in listed.itertuples()
    ])
    for code, rows in idx[idx["species_code"].isin(listed["species_code"])].groupby("species_code"):
        _write(api / "index" / f"{int(code)}.json", {"species_code": int(code), "regions": by_region(rows, INDEX_FIELDS)})
    _write(api / "bottom_temp.json", {"regions": by_region(temp, TEMP_FIELDS)})

    area = strata.set_index("stratum")["area_nmi2"].astype(float)
    regions = index_module.region_strata(strata)
    _write(api / "meta.json", {
        "api_version": 1,
        "release": tag,
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "package_version": version("maritimes-rv"),
        "repository": repository or DEFAULT_REPOSITORY,
        "years": [int(idx["year"].min()), int(idx["year"].max())],
        "regions": {name: {"strata": members, "area_nmi2": round(float(area[members].sum()), 1)}
                    for name, members in regions.items()},
        # Coverage is a property of the region-year, the same for every species
        "incomplete_years": {
            str(region): sorted(int(y) for y in rows.loc[~rows["complete"].astype(bool), "year"].unique())
            for region, rows in idx.groupby("region")
        },
        "vessels": dict(sorted(missions.drop_duplicates("vessel_code").set_index("vessel_code")["vessel_name"].items())),
        "sources": clean_manifest["sources"],
        "fields": {"index": {f: COLUMNS["index"][f] for f in ["year", *INDEX_FIELDS]},
                   "bottom_temp": {f: COLUMNS["bottom_temp"][f] for f in ["year", *TEMP_FIELDS]}},
        "licence": "Contains information licensed under the Open Government Licence - Canada",
    })
    (out_dir / ".nojekyll").write_text("", encoding="utf-8")
    return {"species": len(listed), "files": sum(1 for p in out_dir.rglob("*") if p.is_file())}
