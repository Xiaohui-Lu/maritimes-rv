"""Build the cleaned tables from data/raw and write them to data/clean."""
import hashlib
import json
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

import pandas as pd

from . import clean, index, qc, raw, temperature

CLEAN_TABLES = ("missions", "sets", "catch", "species", "strata", "ctd")


def build_tables(raw_dir: Path) -> dict[str, pd.DataFrame]:
    source = raw.read_all(raw_dir)
    missions = clean.clean_missions(source["GSMISSIONS"])
    strata = clean.clean_strata(source["STRATA"])
    ctd = clean.clean_ctd(source["CTD"])
    sets = temperature.add_ctd_temperature(clean.clean_sets(source["GSINF"], missions), ctd)
    tables = {
        "missions": missions,
        "sets": qc.flag_sets(sets, strata),
        "catch": qc.flag_catch(clean.clean_catch(source["GSCAT"])),
        "species": clean.clean_species(source["GSSPECIES"]),
        "strata": strata,
        "ctd": ctd,
    }
    if problems := qc.validate(tables):
        raise ValueError("integrity checks failed:\n  " + "\n  ".join(problems))
    return tables


def qc_counts(tables: dict[str, pd.DataFrame]) -> dict[str, int]:
    return {
        f"{name}.{column}": int(table[column].sum())
        for name, table in tables.items()
        for column in table.columns
        if column.startswith("qc_")
    }


def write_tables(tables: dict[str, pd.DataFrame], raw_dir: Path, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, table in tables.items():
        table.to_parquet(out_dir / f"{name}.parquet", index=False)
        table.to_csv(out_dir / f"{name}.csv", index=False, lineterminator="\n")

    # Records exactly which source files produced these tables, since DFO may replace them in place.
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "package_version": version("maritimes-rv"),
        "sources": [_describe(path, raw_dir) for path in raw.source_files(raw_dir)],
        "tables": {name: {"rows": len(table), "columns": list(table.columns)} for name, table in tables.items()},
        "qc_counts": qc_counts(tables),
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8", newline="\n")


def _describe(path: Path, raw_dir: Path) -> dict:
    stat = path.stat()
    return {
        "file": path.relative_to(raw_dir).as_posix(),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "bytes": stat.st_size,
        "modified": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(timespec="seconds"),
    }


def build(raw_dir: Path, out_dir: Path) -> dict[str, pd.DataFrame]:
    tables = build_tables(raw_dir)
    write_tables(tables, raw_dir, out_dir)
    return tables


def read_clean(clean_dir: Path) -> dict[str, pd.DataFrame]:
    return {name: pd.read_parquet(clean_dir / f"{name}.parquet") for name in CLEAN_TABLES}


def build_products(clean_dir: Path, out_dir: Path, convert: bool = False,
                   species_codes: list[int] | None = None) -> dict[str, pd.DataFrame]:
    t = read_clean(clean_dir)
    products = {
        "index": index.build_index(t["sets"], t["catch"], t["species"], t["strata"], species_codes, convert),
        "bottom_temp": index.build_bottom_temperature(t["sets"], t["strata"]),
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, table in products.items():
        table.to_parquet(out_dir / f"{name}.parquet", index=False)
        table.to_csv(out_dir / f"{name}.csv", index=False, lineterminator="\n")

    clean_manifest = clean_dir / "manifest.json"
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "package_version": version("maritimes-rv"),
        "clean_manifest_sha256": hashlib.sha256(clean_manifest.read_bytes()).hexdigest() if clean_manifest.exists() else None,
        "parameters": {
            "conversion_factors_applied": convert,
            "standard_tow_nmi": index.STANDARD_TOW_NMI,
            "wingspread_ft": index.WINGSPREAD_FT,
            "complete_area_share": index.COMPLETE_AREA_SHARE,
            "regions": {region: len(members) for region, members in index.region_strata(t["strata"]).items()},
        },
        "tables": {name: {"rows": len(table), "columns": list(table.columns)} for name, table in products.items()},
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8", newline="\n")
    return products
