"""Read the raw DFO files as published, without changing any values."""
import json
from pathlib import Path

import pandas as pd

CSV_DIR = "SUMMER_csv"
CSV_TABLES = ("GSMISSIONS", "GSINF", "GSCAT", "GSSPECIES")
STRATA_FILE = "rest_strata_layer1.json"


def csv_path(raw_dir: Path, table: str) -> Path:
    # File names carry the extraction year (SUMMER_2023_GSINF.csv), which changes with each release.
    matches = sorted((raw_dir / CSV_DIR).glob(f"SUMMER_*_{table}.csv"))
    if len(matches) != 1:
        raise FileNotFoundError(f"expected one SUMMER_*_{table}.csv in {raw_dir / CSV_DIR}, found {len(matches)}")
    return matches[0]


def read_csv_table(raw_dir: Path, table: str) -> pd.DataFrame:
    # The export was written by R, so missing values are the bare string NA. Replacing pandas' default
    # NA list also stops values such as "NAN" or "N/A" from being read as missing by accident.
    # STRAT is a code, not a number: strata such as 5Z1 exist.
    return pd.read_csv(
        csv_path(raw_dir, table),
        keep_default_na=False,
        na_values=["NA", ""],
        dtype={"STRAT": "string"},
    )


def read_strata(raw_dir: Path) -> pd.DataFrame:
    """Strata from an ESRI REST layer 1 query response (see docs/data_notes.md section 6)."""
    payload = json.loads((raw_dir / STRATA_FILE).read_text(encoding="utf-8"))
    return pd.DataFrame([feature["attributes"] for feature in payload["features"]])


def read_all(raw_dir: Path) -> dict[str, pd.DataFrame]:
    tables = {table: read_csv_table(raw_dir, table) for table in CSV_TABLES}
    tables["STRATA"] = read_strata(raw_dir)
    return tables


def source_files(raw_dir: Path) -> list[Path]:
    return [csv_path(raw_dir, table) for table in CSV_TABLES] + [raw_dir / STRATA_FILE]
