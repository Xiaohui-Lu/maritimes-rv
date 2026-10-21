"""Build the cleaned tables from data/raw and write them to data/clean."""
import hashlib
import json
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

import pandas as pd

from . import clean, qc, raw


def build_tables(raw_dir: Path) -> dict[str, pd.DataFrame]:
    source = raw.read_all(raw_dir)
    missions = clean.clean_missions(source["GSMISSIONS"])
    strata = clean.clean_strata(source["STRATA"])
    tables = {
        "missions": missions,
        "sets": qc.flag_sets(clean.clean_sets(source["GSINF"], missions), strata),
        "catch": qc.flag_catch(clean.clean_catch(source["GSCAT"])),
        "species": clean.clean_species(source["GSSPECIES"]),
        "strata": strata,
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
        table.to_csv(out_dir / f"{name}.csv", index=False)

    # Records exactly which source files produced these tables, since DFO may replace them in place.
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "package_version": version("maritimes-rv"),
        "sources": [_describe(path, raw_dir) for path in raw.source_files(raw_dir)],
        "tables": {name: {"rows": len(table), "columns": list(table.columns)} for name, table in tables.items()},
        "qc_counts": qc_counts(tables),
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


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
