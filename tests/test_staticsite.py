import json
import re
import shutil
import subprocess
from importlib import resources
from pathlib import Path

import pandas as pd
import pytest

from maritimes_rv import pipeline, staticsite

RAW = Path(__file__).parents[1] / "data" / "raw"


def strict_json(path):
    # Python's json accepts NaN by default; browsers and other parsers do not
    def reject(constant):
        raise ValueError(f"{path.name} contains {constant}")
    return json.loads(path.read_text(encoding="utf-8"), parse_constant=reject)


def test_columns_become_json_ready_lists():
    assert staticsite.column(pd.Series([1.23456789, None], dtype="Float64")) == [1.23457, None]
    assert staticsite.column(pd.Series([3, None], dtype="Int16")) == [3, None]
    assert staticsite.column(pd.Series([True, None], dtype="boolean")) == [True, None]
    assert staticsite.column(pd.Series(["N", None], dtype="string")) == ["N", None]
    assert staticsite.column(pd.Series([float("nan")])) == [None]


def test_page_loads_nothing_from_other_sites():
    html = resources.files("maritimes_rv").joinpath("site_assets/index.html").read_text(encoding="utf-8")
    external = re.findall(r'<(?:script|link)[^>]+(?:src|href)="(https?:[^"]+)"', html)
    assert external == []
    assert 'src="app.js"' in html and 'href="style.css"' in html


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_app_js_is_valid_javascript():
    app = resources.files("maritimes_rv").joinpath("site_assets/app.js")
    with resources.as_file(app) as path:
        subprocess.run(["node", "--check", str(path)], check=True)


@pytest.mark.skipif(not (RAW / "SUMMER_csv").exists(), reason="data/raw not downloaded")
def test_site_from_real_data(tmp_path):
    pipeline.build(RAW, tmp_path / "clean")
    pipeline.build_products(tmp_path / "clean", tmp_path / "products", species_codes=[10, 11])
    counts = staticsite.build_site(tmp_path / "clean", tmp_path / "products", tmp_path / "site", "data-test")
    api = tmp_path / "site" / "api" / "v1"

    assert {"index.html", "app.js", "style.css"} <= {p.name for p in (tmp_path / "site").iterdir()}
    species = strict_json(api / "species.json")
    assert [s["code"] for s in species] == [11, 10]  # haddock is caught in more tows than cod
    assert counts["species"] == 2

    haddock = strict_json(api / "index" / "11.json")
    assert set(haddock["regions"]) == {"core", "4VW", "4X5Y"}
    region = haddock["regions"]["4X5Y"]
    assert {len(values) for values in region.values()} == {54}
    year_2021 = region["year"].index(2021)
    assert region["complete"][year_2021] is False and region["n_sets"][year_2021] == 2

    meta = strict_json(api / "meta.json")
    assert meta["release"] == "data-test" and meta["years"] == [1970, 2023]
    assert meta["incomplete_years"] == {"4VW": [2018, 2021, 2022], "4X5Y": [2021], "core": [2018, 2021, 2022]}
    assert meta["vessels"]["N"] == "CCGS Alfred Needler"
    assert set(meta["fields"]["index"]) >= {"year", "mean_weight_kg_per_tow", "complete"}

    temp = strict_json(api / "bottom_temp.json")["regions"]["4X5Y"]
    assert temp["n_sets_with_temp"][temp["year"].index(2005)] == 0
