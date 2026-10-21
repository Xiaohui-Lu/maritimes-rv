"""A deliberately naive, line-by-line port of DFO's RVTransmogrifier stratified estimate, for cross-checking.

It follows stratify_simple(), calcYearSummary(), calcTotalMean(), calcTotalSE_stratified(),
valPerSqKm() and sqNMToSqKm() in github.com/Maritimes/RVTransmogrifier (R/stratify.R, R/000-utils.R)
and st_err() in Maritimes/Mar.utils, including DFO's rule that missing TOTNO counts as 0. It loops
year by year and stratum by stratum instead of vectorising, so it shares no code with index.py.

Usage: uv run python validation/rvtransmogrifier_port.py [data/clean] [data/products]
Expected: rows without missing counts agree to floating-point precision for the mean and SE, and to
about 1e-6 for totals (DFO rounds the nmi2 -> km2 factor to 3.4299); rows with missing counts differ.
"""
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

SPECIES = [10, 11, 14, 40, 41, 42, 43, 8600]  # cod, haddock, silver hake, 4 flatfish, sponges


def val_per_sqkm(values, tow_nmi, wingspread_ft=41):
    values = np.nan_to_num(values)
    swept_km2 = (wingspread_ft * 0.3048 / 1000) * (tow_nmi * 1.1507794 * 5280 * 0.3048 / 1000)
    return values / swept_km2


def st_err(x):
    return np.nan if len(x) < 2 else np.std(x, ddof=1) / math.sqrt(len(x))


def port(clean: Path) -> pd.DataFrame:
    sets = pd.read_parquet(clean / "sets.parquet")
    sets = sets[~sets["qc_comparative_fishing"]]
    catch = pd.read_parquet(clean / "catch.parquet")
    strata = pd.read_parquet(clean / "strata.parquet")
    area_km2 = dict(zip(strata["stratum"], (strata["area_nmi2"].astype(float) * 3.4299).round(4)))
    regions = {"core": strata.loc[strata["is_core"], "stratum"].tolist(),
               "4X5Y": strata.loc[strata["area_group"].fillna("") == "4X5Y", "stratum"].tolist()}

    rows = []
    for code in SPECIES:
        caught = catch.loc[catch["species_code"] == code, ["mission", "setno", "count_std"]]
        for region, members in regions.items():
            for year, tows in sets[sets["stratum"].isin(members)].groupby("year"):
                df = tows.merge(caught, on=["mission", "setno"], how="left")
                totno = df["count_std"].astype(float).fillna(0).to_numpy()  # DFO: NA -> 0
                density = val_per_sqkm(totno, 1.75)  # our catches are already per 1.75 nmi tow
                by_stratum = []
                for stratum, g in df.assign(TOTNO=totno, DENS=density).groupby("stratum"):
                    a = area_km2[stratum]
                    by_stratum.append({"A": a, "mean": g["TOTNO"].mean(), "se": st_err(g["TOTNO"].to_numpy()),
                                       "abund": g["DENS"].mean() * a, "abund_se": st_err((g["DENS"] * a).to_numpy())})
                st = pd.DataFrame(by_stratum)
                with_se = st[st["se"].notna()]
                rows.append({
                    "region": region, "year": year, "species_code": code,
                    "dfo_mean": (st["mean"] * st["A"] / st["A"].sum()).sum(),
                    "dfo_se": math.sqrt(((with_se["A"] / with_se["A"].sum()) ** 2 * with_se["se"] ** 2).sum()),
                    "dfo_total": st["abund"].sum(),
                    "dfo_total_se": math.sqrt((st["abund_se"].dropna() ** 2).sum()),
                })
    return pd.DataFrame(rows)


def main(clean: Path, products: Path) -> None:
    ours = pd.read_parquet(products / "index.parquet")
    both = port(clean).merge(ours, on=["region", "year", "species_code"])
    pairs = [("dfo_mean", "mean_count_per_tow"), ("dfo_se", "se_count_per_tow"),
             ("dfo_total", "total_count"), ("dfo_total_se", "se_total_count")]
    for label, rows in [("no missing counts", both[both["n_count_missing"] == 0]),
                        ("with missing counts", both[both["n_count_missing"] > 0])]:
        print(f"{label}: {len(rows)} rows (species {sorted(rows['species_code'].unique())})")
        for theirs, mine in pairs:
            rel = (rows[theirs] - rows[mine].astype(float)).abs() / rows[theirs].abs().clip(lower=1e-9)
            print(f"  {mine:<20} max relative difference {rel.max():.1e}")


if __name__ == "__main__":
    args = [Path(a) for a in sys.argv[1:]]
    main(*(args or [Path("data/clean"), Path("data/products")]))
