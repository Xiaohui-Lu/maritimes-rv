"""Profile the raw DFO Maritimes summer RV survey export. Usage: python profile_raw.py data/raw"""
import json
import sys
from pathlib import Path

import pandas as pd

pd.set_option("display.width", 200)
pd.set_option("display.max_columns", 50)
pd.set_option("display.max_rows", 200)

raw = Path(sys.argv[1])
csv_dir = raw / "SUMMER_csv"


def load(name):
    # keep_default_na=False + na_values=["NA"]: the export is from R, which writes missing as bare NA
    return pd.read_csv(csv_dir / f"SUMMER_2023_{name}.csv", keep_default_na=False, na_values=["NA", ""])


def section(title):
    print(f"\n{'=' * 20} {title} {'=' * 20}")


def profile(df, name):
    section(f"{name}: {len(df):,} rows x {df.shape[1]} cols")
    summary = pd.DataFrame({
        "dtype": df.dtypes.astype(str),
        "n_null": df.isna().sum(),
        "pct_null": (df.isna().mean() * 100).round(2),
        "n_unique": df.nunique(),
    })
    print(summary)
    num = df.select_dtypes("number")
    if not num.empty:
        print(num.describe().T)


section("Excel data dictionary (DataDictionary_202008.xlsx)")
xl = pd.read_excel(csv_dir / "DataDictionary_202008.xlsx", sheet_name=None)
for sheet, d in xl.items():
    print(f"\n--- sheet: {sheet} ({d.shape}) ---")
    print(d.to_string())

missions = load("GSMISSIONS")
inf = load("GSINF")
cat = load("GSCAT")
species = load("GSSPECIES")

profile(missions, "GSMISSIONS")
print("\nYEAR range:", missions.YEAR.min(), "-", missions.YEAR.max())
print("SEASON:", missions.SEASON.value_counts().to_dict())
print("VESEL:", missions.VESEL.value_counts().to_dict())
print("missions per year (years with >1):")
mpy = missions.groupby("YEAR").MISSION.apply(list)
print(mpy[mpy.str.len() > 1].to_string())
all_years = set(range(missions.YEAR.min(), missions.YEAR.max() + 1))
print("years with no mission:", sorted(all_years - set(missions.YEAR)))

profile(inf, "GSINF")
inf["SDATE"] = pd.to_datetime(inf.SDATE)
inf["YEAR"] = inf.SDATE.dt.year
print("\nSDATE range:", inf.SDATE.min().date(), "-", inf.SDATE.max().date())
print("months:", inf.SDATE.dt.month.value_counts().sort_index().to_dict())
print("dup (MISSION, SETNO):", inf.duplicated(["MISSION", "SETNO"]).sum())
print("\nsets per year:")
print(inf.groupby("YEAR").size().to_string())
print("\nGEARDESC:")
print(inf.GEARDESC.value_counts(dropna=False).to_string())
print("\ngear by year range:")
print(inf.groupby("GEARDESC").YEAR.agg(["min", "max", "count"]).to_string())
print("\nSTRAT values (sorted):")
print(sorted(inf.STRAT.astype(str).unique()))
print("\nBOTT_TEMP / BOTT_SAL / SURF_TEMP % missing by decade:")
inf["DECADE"] = inf.YEAR // 10 * 10
print(inf.groupby("DECADE")[["BOTT_TEMP", "BOTT_SAL", "SURF_TEMP", "ELAT", "DIST", "DEPTH"]]
      .apply(lambda g: (g.isna().mean() * 100).round(1)).to_string())
print("\nsuspicious values:")
print("  DUR <= 0 or > 60:", ((inf.DUR <= 0) | (inf.DUR > 60)).sum())
print("  DIST <= 0:", (inf.DIST <= 0).sum(), " DIST > 4:", (inf.DIST > 4).sum())
print("  BOTT_TEMP < -2 or > 20:", ((inf.BOTT_TEMP < -2) | (inf.BOTT_TEMP > 20)).sum())
print("  BOTT_SAL < 25 or > 37:", ((inf.BOTT_SAL < 25) | (inf.BOTT_SAL > 37)).sum())
print("  SLAT outside 39-48:", (~inf.SLAT.between(39, 48)).sum(), " SLONG outside -72..-55:", (~inf.SLONG.between(-72, -55)).sum())
print("  TIME > 2359 or minutes >= 60:", ((inf.TIME > 2359) | (inf.TIME % 100 >= 60)).sum())

profile(cat, "GSCAT")
print("\ndup (MISSION, SETNO, SPEC):", cat.duplicated(["MISSION", "SETNO", "SPEC"]).sum())
print("TOTWGT == 0:", (cat.TOTWGT == 0).sum(), "  TOTNO == 0:", (cat.TOTNO == 0).sum())
print("TOTNO == 0 & TOTWGT > 0:", ((cat.TOTNO == 0) & (cat.TOTWGT > 0)).sum())
print("TOTNO non-integer:", (cat.TOTNO.dropna() % 1 != 0).sum())
print("TOTWGT with > 3 decimals (i.e. not raw grams):", ((cat.TOTWGT * 1000).round(6) % 1 != 0).sum())

section("Referential integrity")
inf_keys = set(zip(inf.MISSION, inf.SETNO))
cat_keys = set(zip(cat.MISSION, cat.SETNO))
print("GSCAT (MISSION,SETNO) not in GSINF:", len(cat_keys - inf_keys))
print("GSINF sets with no GSCAT rows at all:", len(inf_keys - cat_keys))
print("GSINF MISSION not in GSMISSIONS:", sorted(set(inf.MISSION) - set(missions.MISSION)))
print("GSMISSIONS MISSION not in GSINF:", sorted(set(missions.MISSION) - set(inf.MISSION)))
print("GSCAT SPEC not in GSSPECIES:", sorted(set(cat.SPEC) - set(species.CODE)))

section("Tow-distance standardisation check")
# Hypothesis: TOTWGT is already scaled to a standard 1.75 nm tow, i.e. TOTWGT = raw * 1.75 / DIST.
m = cat.merge(inf[["MISSION", "SETNO", "DIST"]], on=["MISSION", "SETNO"])
m = m[(m.DIST > 0) & (m.DIST.round(2) != 1.75)]
back = m.TOTWGT * m.DIST / 1.75
def frac_round(s, d=3):
    return ((s * 10**d).round(6) % 1 == 0).mean()
print(f"rows with DIST != 1.75: {len(m):,}")
print(f"  share of TOTWGT that is a whole number of grams:              {frac_round(m.TOTWGT):.1%}")
print(f"  share of TOTWGT*DIST/1.75 that is ~ a whole number of grams: {((back * 1000 - (back * 1000).round()).abs() < 1e-3).mean():.1%}")
back_no = m.TOTNO * m.DIST / 1.75
print(f"  share of TOTNO that is an integer:              {(m.TOTNO.dropna() % 1 == 0).mean():.1%}")
print(f"  share of TOTNO*DIST/1.75 that is ~ an integer:  {((back_no - back_no.round()).abs() < 1e-3).mean():.1%}")
sample = m.assign(wgt_raw=back.round(5), no_raw=back_no.round(3)).sample(8, random_state=1)[
    ["MISSION", "SETNO", "SPEC", "DIST", "TOTWGT", "wgt_raw", "TOTNO", "no_raw"]]
print(sample.to_string())

section("Extra checks")
print("missions 2007+:")
print(missions[missions.YEAR >= 2007].to_string(index=False))
print("\nvessel by year range:")
print(missions.groupby("VESEL").YEAR.agg(["min", "max", "count"]).to_string())
print("\n% missing BOTT_TEMP by year 2015+ (n sets):")
recent = inf[inf.YEAR >= 2015]
print(recent.groupby("YEAR").agg(n=("SETNO", "size"),
                                 bott_temp_missing_pct=("BOTT_TEMP", lambda s: round(s.isna().mean() * 100, 1))).to_string())
print("\nBOTT_TEMP missing by mission in 2020s:")
print(inf[inf.YEAR >= 2020].groupby("MISSION").BOTT_TEMP.agg(["size", lambda s: s.isna().sum()]).to_string())
print("\nDEPTH: share that is a whole number of fathoms (DEPTH / 1.8288):")
d = inf.DEPTH.dropna() / 1.8288
print(f"  {((d - d.round()).abs() < 1e-3).mean():.1%}")
print("\nSPEED > 6 knots:")
print(inf[inf.SPEED > 6][["MISSION", "SETNO", "DUR", "DIST", "SPEED"]].to_string(index=False))
print("\nDUR value counts:", inf.DUR.value_counts().sort_index().to_dict())
print("\nGSCAT rows with SPEC NaN:")
print(cat[cat.SPEC.isna()].to_string(index=False))
print("\nGSCAT TOTWGT==0 & TOTNO>0:", ((cat.TOTWGT == 0) & (cat.TOTNO > 0)).sum(),
      "  both 0:", ((cat.TOTWGT == 0) & (cat.TOTNO == 0)).sum(),
      "  TOTWGT NaN:", cat.TOTWGT.isna().sum(), "  TOTNO NaN:", cat.TOTNO.isna().sum())
print("SPEC >= 9000 in GSSPECIES:")
print(species[species.CODE >= 9000].to_string(index=False))
print("\nStratum-years with < 2 sets (stratified variance needs >= 2):")
spy = inf.groupby(["YEAR", "STRAT"]).size()
lt2 = spy[spy < 2]
print(f"  {len(lt2)} of {len(spy)} stratum-years; by year: {lt2.groupby(level=0).size().to_dict()}")
print("strata sampled per year (min/median/max):",
      inf.groupby("YEAR").STRAT.nunique().agg(["min", "median", "max"]).to_dict())
print("years with < 40 strata sampled:", inf.groupby("YEAR").STRAT.nunique().loc[lambda s: s < 40].to_dict())

profile(species, "GSSPECIES")
print("dup CODE:", species.CODE.duplicated().sum())
print("\nTop 15 species by number of sets where caught:")
top = (cat.groupby("SPEC").size().rename("n_sets").reset_index()
       .merge(species, left_on="SPEC", right_on="CODE", how="left")
       .sort_values("n_sets", ascending=False).head(15))
print(top[["SPEC", "SCI_NAME", "COMM", "n_sets"]].to_string(index=False))

section("Strata table (data/raw/rest_strata_layer1.json, from ESRI REST layer 1)")
strata_file = raw / "rest_strata_layer1.json"
if strata_file.exists():
    strata = (pd.DataFrame([f["attributes"] for f in json.loads(strata_file.read_text(encoding="utf-8"))["features"]])
              .rename(columns={"DEPTH": "NOMINAL_DEPTH"}))
    inf["STRAT"] = inf.STRAT.astype(str)
    print("strata in table:", len(strata), "| GSINF strata missing from table:", sorted(set(inf.STRAT) - set(strata.STRAT)))
    d = inf.dropna(subset=["DEPTH"]).merge(strata, on="STRAT")
    # Units are not documented: test which unit makes tow depths fall inside their stratum's depth band.
    for label, depth in [("DEPTH as metres", d.DEPTH), ("DEPTH converted to fathoms", d.DEPTH / 1.8288)]:
        print(f"  {label:28s}: {depth.between(d.DMIN - 5, d.DMAX + 5).mean():.1%} of sets inside [DMIN, DMAX] +/-5")
else:
    print("not found; see docs/data_notes.md for the REST query")
