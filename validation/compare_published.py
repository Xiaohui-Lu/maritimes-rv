"""Compare data/products/index.parquet with indices transcribed from published DFO documents.

Usage: uv run python validation/compare_published.py [data/products]
Sources and transcription notes are in the header of each file in validation/published/.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PUBLISHED = Path(__file__).parent / "published"


def read(name: str) -> pd.DataFrame:
    return pd.read_csv(PUBLISHED / name, comment="#")


def ours(index: pd.DataFrame, region: str, species_code: int, column: str) -> pd.Series:
    rows = index[(index["region"] == region) & (index["species_code"] == species_code)]
    return rows.set_index("year")[column].astype(float)


def haddock_4x5y(index: pd.DataFrame) -> pd.DataFrame:
    """Stone & Hansen (2015) Table 9: 4X5Y total biomass (t), with x1.2 applied to 1970-81 in the paper."""
    published = read("stone_hansen_2015_haddock_4x5y.csv").set_index("year")["combined_t"]
    mine = ours(index, "4X5Y", 11, "total_weight_t")
    mine = mine.where(mine.index > 1981, mine * 1.2)
    return pd.DataFrame({"ours": mine, "published": published}).dropna()


def flatfish_4x(index: pd.DataFrame, species_code: int, metric: str) -> pd.DataFrame:
    columns = {"number": ("mean_count_per_tow", "mean_number_per_tow"),
               "kg": ("mean_weight_kg_per_tow", "mean_kg_per_tow"),
               "se_kg": ("se_weight_kg_per_tow", "se_kg_per_tow")}
    mine, theirs = columns[metric]
    table = read("stobo_1997_flatfish_4x.csv")
    published = table[table["species_code"] == species_code].set_index("year")[theirs]
    return pd.DataFrame({"ours": ours(index, "4X5Y", species_code, mine), "published": published}).dropna()


def pollock_4vwx(index: pd.DataFrame) -> pd.DataFrame:
    published = read("trippel_brown_1993_pollock_4vwx.csv").set_index("year")["mean_number_per_tow"]
    return pd.DataFrame({"ours": ours(index, "core", 16, "mean_count_per_tow"), "published": published}).dropna()


def summarise(label: str, df: pd.DataFrame) -> None:
    ratio = df["ours"] / df["published"]
    off = (ratio - 1).abs()
    worst = off.sort_values(ascending=False).head(4).index
    print(f"{label:<44} {len(df):>3} yrs  median ratio {ratio.median():.3f}  "
          f"within 1%: {(off <= .01).mean():>4.0%}  within 5%: {(off <= .05).mean():>4.0%}  "
          f"largest: {', '.join(f'{y} ({ratio[y]:.2f})' for y in worst)}")


def main(products: Path) -> None:
    index = pd.read_parquet(products / "index.parquet")
    summarise("Haddock 4X5Y total biomass (Stone & Hansen 2015)", haddock_4x5y(index))
    for code, name in [(43, "winter flounder"), (40, "American plaice"), (42, "yellowtail")]:
        for metric in ("number", "kg", "se_kg"):
            summarise(f"{name} 4X {metric}/tow (Stobo et al. 1997)", flatfish_4x(index, code, metric))
    summarise("Pollock 4VWX number/tow (Trippel & Brown 1993)", pollock_4vwx(index))


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/products"))
