"""End-to-end checks on the real DFO files; skipped when data/raw is not present."""
import json
from pathlib import Path

import pandas as pd
import pytest

from maritimes_rv import pipeline

RAW = Path(__file__).parents[1] / "data" / "raw"
pytestmark = pytest.mark.skipif(not (RAW / "SUMMER_csv").exists(), reason="data/raw not downloaded")


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    out = tmp_path_factory.mktemp("clean")
    return pipeline.build(RAW, out), out


def test_row_counts_match_step_1_profile(built):
    tables, _ = built
    assert {name: len(t) for name, t in tables.items()} == {
        "missions": 94, "sets": 9437, "catch": 139465, "species": 649, "strata": 72,
    }


def test_zero_rules_from_data_model(built):
    catch = built[0]["catch"]
    assert not (catch["count_std"] == 0).any()
    assert catch["qc_weight_zero"].sum() == 8861


def test_comparative_fishing_flags_exactly_the_two_calibration_missions(built):
    sets = built[0]["sets"]
    assert set(sets.loc[sets["qc_comparative_fishing"], "mission"]) == {"HAM1981060", "TEL2005605"}


def test_parquet_round_trip_keeps_types(built):
    tables, out = built
    sets = pd.read_parquet(out / "sets.parquet")
    assert sets["stratum"].dtype == tables["sets"]["stratum"].dtype
    assert sets["setno"].dtype == "Int16"
    assert sets["end_lat"].isna().sum() == tables["sets"]["end_lat"].isna().sum()


def test_manifest_records_sources_and_rows(built):
    _, out = built
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert {s["file"] for s in manifest["sources"]} >= {"rest_strata_layer1.json"}
    assert all(len(s["sha256"]) == 64 for s in manifest["sources"])
    assert manifest["tables"]["sets"]["rows"] == 9437
