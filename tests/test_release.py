import hashlib
import json
import zipfile
from pathlib import Path

import pandas as pd
import pytest

from maritimes_rv import fetch, pipeline, release

RAW = Path(__file__).parents[1] / "data" / "raw"


def test_data_dictionary_rejects_undocumented_and_stale_columns():
    with pytest.raises(ValueError, match=r"without a description \['surprise'\]"):
        release.data_dictionary({"species": pd.DataFrame(columns=[*release.COLUMNS["species"], "surprise"])})
    with pytest.raises(ValueError, match=r"descriptions without a column \['is_taxon'\]"):
        release.data_dictionary({"species": pd.DataFrame(columns=["species_code", "scientific_name", "common_name"])})


def test_incomplete_years_are_listed_per_region():
    table = pd.DataFrame({"region": ["4VW", "4VW", "4X5Y", "4VW"], "year": [2018, 2021, 2021, 2019],
                          "complete": [False, False, False, True]})
    assert release._incomplete_years(table) == "  - 4VW: 2018, 2021\n  - 4X5Y: 2021"
    assert release._incomplete_years(table.assign(complete=True)) == "  - none"


@pytest.mark.skipif(not (RAW / "SUMMER_csv").exists(), reason="data/raw not downloaded")
def test_release_package_from_real_data(tmp_path):
    pipeline.build(RAW, tmp_path / "clean")
    pipeline.build_products(tmp_path / "clean", tmp_path / "products", species_codes=[11])
    files = release.build_release(tmp_path / "clean", tmp_path / "products", RAW, tmp_path / "dist", "test")
    archive, sources, checksums, notes = files

    with zipfile.ZipFile(archive) as z:
        names = set(z.namelist())
        readme = z.read("maritimes-rv-data-test/README.md").decode()
        dictionary = pd.read_csv(z.open("maritimes-rv-data-test/data_dictionary.csv"))
    for table in ("clean/sets", "clean/catch", "products/index", "products/bottom_temp"):
        assert {f"maritimes-rv-data-test/{table}.parquet", f"maritimes-rv-data-test/{table}.csv"} <= names
    assert "1970-2023" in readme and "4X5Y: 2021" in readme and "not applied" in readme
    assert len(dictionary) == sum(len(c) for c in release.COLUMNS.values())

    assert json.loads(sources.read_text()) == fetch.fingerprint(RAW)
    assert b"\r\n" not in sources.read_bytes()
    expected = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (archive, sources)}
    assert dict(reversed(line.split("  ")) for line in checksums.read_text().splitlines()) == expected
    assert "Open Government Licence" in notes.read_text()
