"""Regression test against a published DFO index; skipped when data/raw is not present."""
from pathlib import Path

import pandas as pd
import pytest

from maritimes_rv import index, pipeline

ROOT = Path(__file__).parents[1]
RAW = ROOT / "data" / "raw"
pytestmark = pytest.mark.skipif(not (RAW / "SUMMER_csv").exists(), reason="data/raw not downloaded")


def test_haddock_4x5y_matches_stone_and_hansen_2015_within_one_percent():
    t = pipeline.build_tables(RAW)
    ours = index.build_index(t["sets"], t["catch"], t["species"], t["strata"], [11])
    ours = ours[ours["region"] == "4X5Y"].set_index("year")["total_weight_t"].astype(float)
    ours = ours.where(ours.index > 1981, ours * 1.2)  # the paper applies Fanning's x1.2 to 1970-81

    published = pd.read_csv(ROOT / "validation" / "published" / "stone_hansen_2015_haddock_4x5y.csv",
                            comment="#").set_index("year")["combined_t"]
    ratio = (ours / published).dropna()
    assert len(ratio) == 45
    assert ratio.between(0.99, 1.01).all(), ratio[~ratio.between(0.99, 1.01)]
