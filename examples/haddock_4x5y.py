"""Example analysis: 4X5Y haddock in the DFO Maritimes summer research vessel survey.

Run after `maritimes-rv clean` and `maritimes-rv index`:

    uv run --group examples python examples/haddock_4x5y.py

Writes three figures and the table behind them to examples/figures/, and prints every number
quoted in examples/haddock_4x5y.md so the write-up can be checked against the data.
"""
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from maritimes_rv import index, pipeline

ROOT = Path(__file__).parents[1]
OUT = Path(__file__).parent / "figures"
HADDOCK, REGION = 11, "4X5Y"
GEAR_CHANGE = 1981.5  # Yankee #36 trawl (A.T. Cameron) up to 1981, Western IIA from 1982

# Reference chart palette: surface, ink and two categorical slots (validated for colour-vision deficiency)
SURFACE, INK, INK_2, MUTED = "#fcfcfb", "#0b0b0b", "#52514e", "#898781"
GRID, BASELINE = "#e1e0d9", "#c3c2b7"
BLUE, ORANGE = "#2a78d6", "#eb6834"
SOURCE = ("Source: DFO Maritimes Summer Research Vessel Survey open data, Open Government Licence - Canada. "
          "Computed with maritimes-rv.")
SOURCE_WITH_CTD = ("Sources: DFO Maritimes summer RV survey open data; DFO BIO CTD profiles via CIOOS Atlantic. "
                   "Open Government Licence - Canada.")


def style() -> None:
    plt.rcParams.update({
        "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
        "font.family": "sans-serif", "font.sans-serif": ["Segoe UI", "Helvetica Neue", "Arial", "DejaVu Sans"],
        "font.size": 9, "text.color": INK, "axes.labelcolor": INK_2, "axes.labelsize": 9,
        "xtick.color": BASELINE, "ytick.color": BASELINE, "xtick.labelcolor": MUTED, "ytick.labelcolor": MUTED,
        "axes.grid": True, "axes.grid.axis": "y", "grid.color": GRID, "grid.linewidth": 0.75, "grid.linestyle": "-",
        "axes.spines.top": False, "axes.spines.right": False, "axes.spines.left": False,
        "axes.edgecolor": BASELINE, "axes.linewidth": 0.75, "ytick.left": False,
        "lines.linewidth": 1.5, "lines.solid_capstyle": "round", "lines.solid_joinstyle": "round",
    })


def panel_title(ax, text: str) -> None:
    ax.set_title(text, loc="left", fontsize=9.5, color=INK, fontweight="semibold", pad=6)


def series_with_band(ax, years, mean, se, complete, color=BLUE) -> None:
    """Line through complete years, a 95% band, and incomplete years as separate grey points."""
    shown = mean.where(complete)
    ax.fill_between(years, (shown - 1.96 * se).clip(lower=0), shown + 1.96 * se, color=color, alpha=0.10, lw=0)
    ax.plot(years, shown, color=color)
    # A complete year between two gaps has no line segment, so it needs a marker to be visible at all
    isolated = shown.notna() & shown.shift(1).isna() & shown.shift(-1).isna()
    ax.plot(years[isolated.to_numpy()], shown[isolated], "o", ms=5, color=color, mec=SURFACE, mew=1.5, zorder=3)
    if isolated.any():
        lower, upper = (shown - 1.96 * se).clip(lower=0)[isolated], (shown + 1.96 * se)[isolated]
        ax.vlines(years[isolated.to_numpy()], lower, upper, color=color, alpha=0.35, lw=2)
    partial = ~complete & mean.notna()
    ax.plot(years[partial], mean[partial], "o", ms=6, color=MUTED, mec=SURFACE, mew=1.5, zorder=3)


def gear_change(ax, label: bool) -> None:
    ax.axvline(GEAR_CHANGE, color=BASELINE, lw=0.75, zorder=0)
    if label:
        top = ax.get_ylim()[1]
        ax.text(GEAR_CHANGE - 0.6, top, "Yankee #36 trawl", ha="right", va="top", color=MUTED, fontsize=8)
        ax.text(GEAR_CHANGE + 0.6, top, "Western IIA trawl", ha="left", va="top", color=MUTED, fontsize=8)


def header(fig, title: str, subtitle: str, source: str = SOURCE) -> None:
    # Offsets in inches, so the header keeps its spacing whatever the figure height
    height = fig.get_figheight()
    fig.text(0.02, 1 - 0.14 / height, title, ha="left", va="top", fontsize=12, fontweight="semibold", color=INK)
    fig.text(0.02, 1 - 0.42 / height, subtitle, ha="left", va="top", fontsize=9, color=INK_2)
    fig.text(0.02, 0.08 / height, source, ha="left", va="bottom", fontsize=7, color=MUTED)


def load():
    products = ROOT / "data" / "products"
    ix = pd.read_parquet(products / "index.parquet")
    h = ix[(ix["region"] == REGION) & (ix["species_code"] == HADDOCK)].set_index("year").sort_index()
    bt = pd.read_parquet(products / "bottom_temp.parquet")
    bt = bt[bt["region"] == REGION].set_index("year").sort_index()
    published = pd.read_csv(ROOT / "validation" / "published" / "stone_hansen_2015_haddock_4x5y.csv",
                            comment="#").set_index("year")["combined_t"]
    return h, bt, published


def figure_trends(h: pd.DataFrame) -> None:
    years = h.index.to_numpy(int)
    complete = h["complete"].astype(bool)
    kg_per_fish = (h["mean_weight_kg_per_tow"] / h["mean_count_per_tow"]).astype(float)

    fig, axes = plt.subplots(3, 1, figsize=(7.5, 7.8), sharex=True)
    fig.subplots_adjust(left=0.08, right=0.97, top=0.85, bottom=0.07, hspace=0.38)
    series_with_band(axes[0], years, h["mean_weight_kg_per_tow"].astype(float), h["se_weight_kg_per_tow"].astype(float), complete)
    panel_title(axes[0], "Biomass: kg per standard tow")
    series_with_band(axes[1], years, h["mean_count_per_tow"].astype(float), h["se_count_per_tow"].astype(float), complete)
    panel_title(axes[1], "Abundance: fish per standard tow")
    axes[2].plot(years, kg_per_fish.where(complete), color=BLUE)
    panel_title(axes[2], "Average weight of a fish caught (kg) = biomass / abundance")

    for i, ax in enumerate(axes):
        ax.set_ylim(bottom=0)
        gear_change(ax, label=i == 0)
    axes[2].set_xlim(1969, 2024)
    partial = ", ".join(f"{y} ({int(h.loc[y, 'n_sets'])} tows)" for y in h.index[~complete])
    header(fig, "4X5Y haddock, DFO Maritimes summer survey, 1970-2023",
           "Stratified means over strata 470-495 with 95% intervals (±1.96 SE). No vessel conversion applied.\n"
           f"Grey point: incomplete survey coverage, not comparable - {partial}.")
    fig.savefig(OUT / "haddock_4x5y_trends.png", dpi=200)
    plt.close(fig)


def figure_validation(h: pd.DataFrame, published: pd.Series, before_fix_2005: float) -> pd.DataFrame:
    ours = h["total_weight_t"].astype(float)
    ours = ours.where(ours.index > 1981, ours * 1.2)  # the paper applies Fanning's x1.2 to 1970-81
    both = pd.DataFrame({"ours": ours, "published": published}).dropna()
    diff_pct = (both["ours"] / both["published"] - 1) * 100

    fig, (top, bottom) = plt.subplots(2, 1, figsize=(7.5, 6.2), sharex=True, gridspec_kw={"height_ratios": [2.2, 1]})
    fig.subplots_adjust(left=0.09, right=0.97, top=0.85, bottom=0.09, hspace=0.30)
    top.plot(both.index, both["ours"] / 1000, color=BLUE, label="maritimes-rv (this project)", zorder=2)
    top.plot(both.index, both["published"] / 1000, "o", ms=6, color=ORANGE, mec=SURFACE, mew=1.5,
             label="Stone & Hansen (2015), Table 9", zorder=3)
    top.set_ylim(bottom=0)
    top.legend(loc="upper right", frameon=False, fontsize=8, labelcolor=INK_2)
    panel_title(top, "Total biomass index (thousand tonnes)")

    bottom.axhspan(-1, 1, color=GRID, alpha=0.6, lw=0)
    bottom.axhline(0, color=BASELINE, lw=0.75)
    bottom.plot(diff_pct.index, diff_pct, "o", ms=5, color=BLUE, mec=SURFACE, mew=1.2, zorder=3)
    bottom.set_ylim(-1.5, 1.5)
    bottom.set_yticks([-1, 0, 1], ["-1%", "0", "+1%"])
    panel_title(bottom, "Difference from published value (grey band = ±1%)")
    bottom.annotate(f"2005 was +{before_fix_2005:.0f}% before comparative-fishing\ntows were excluded",
                    (2005, diff_pct.loc[2005]), xytext=(-12, -30), textcoords="offset points", ha="right",
                    fontsize=8, color=INK_2, arrowprops={"arrowstyle": "-", "color": MUTED, "lw": 0.75})
    for ax in (top, bottom):
        gear_change(ax, label=False)
    header(fig, "Validation: 4X5Y haddock against a published DFO index",
           "Same strata (470-495), summer survey, x1.2 vessel conversion on 1970-81 as in the paper.")
    fig.savefig(OUT / "haddock_4x5y_validation.png", dpi=200)
    plt.close(fig)
    return both.assign(diff_pct=diff_pct)


def figure_bottom_temperature(bt: pd.DataFrame) -> None:
    # Keep every year, so a year without readings breaks the line instead of being bridged
    years = bt.index.to_numpy(int)
    fig, ax = plt.subplots(figsize=(7.5, 3.9))
    fig.subplots_adjust(left=0.08, right=0.97, top=0.70, bottom=0.14)
    series_with_band(ax, years, bt["mean_bottom_temp_c"].astype(float), bt["se_bottom_temp_c"].astype(float),
                     bt["complete"].astype(bool))
    panel_title(ax, "Bottom temperature (°C)")
    ax.set_xlim(1969, 2024)
    no_readings = [int(y) for y in bt.index[bt["n_sets_with_temp"] == 0]]
    partial = [int(y) for y in bt.index[~bt["complete"].astype(bool) & (bt["n_sets_with_temp"] > 0)]]
    from_ctd = [int(y) for y in bt.index[bt["n_from_ctd"] > bt["n_sets_with_temp"] / 2]]
    header(fig, "Bottom temperature in 4X5Y during the summer survey, 1970-2023",
           "Stratified mean with 95% interval (±1.96 SE). Survey readings; where missing, the CTD cast at the same\n"
           f"station (mostly CTD in {', '.join(map(str, from_ctd))}). No readings: {', '.join(map(str, no_readings))}. "
           f"Grey points: under 90% of the area ({', '.join(map(str, partial))}).", source=SOURCE_WITH_CTD)
    fig.savefig(OUT / "bottom_temperature_4x5y.png", dpi=200)
    plt.close(fig)


def haddock_2005_without_flag() -> float:
    """Percent difference for 2005 if comparative-fishing tows were kept (as before the fix)."""
    t = pipeline.read_clean(ROOT / "data" / "clean")
    sets = t["sets"].assign(qc_comparative_fishing=False)
    sets = sets[sets["year"] == 2005]
    total = index.build_index(sets, t["catch"], t["species"], t["strata"], [HADDOCK])
    return float(total.set_index("region").loc[REGION, "total_weight_t"])


def largest_tow_share(year: int) -> tuple[float, str]:
    """Share of a year's stratified mean (kg/tow) contributed by its single largest tow."""
    t = pipeline.read_clean(ROOT / "data" / "clean")
    sets = index.survey_tows(t["sets"])
    members = index.region_strata(t["strata"])[REGION]
    tows = index.zero_fill(sets[(sets["year"] == year) & sets["stratum"].isin(members)], t["catch"], HADDOCK)
    area = t["strata"].set_index("stratum")["area_nmi2"].astype(float)
    sampled_area = area[tows["stratum"].unique()].sum()
    weight = tows["stratum"].map(area) / sampled_area / tows["stratum"].map(tows["stratum"].value_counts())
    contribution = tows["weight_kg_std"].astype(float) * weight
    top = contribution.idxmax()
    return contribution[top] / contribution.sum(), f"{tows.loc[top, 'mission']} set {tows.loc[top, 'setno']}: {float(tows.loc[top, 'weight_kg_std']):,.0f} kg"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    style()
    h, bt, published = load()
    before_fix = (haddock_2005_without_flag() / published[2005] - 1) * 100

    figure_trends(h)
    validation = figure_validation(h, published, before_fix)
    figure_bottom_temperature(bt)

    table = pd.DataFrame({
        "n_sets": h["n_sets"], "complete": h["complete"],
        "kg_per_tow": h["mean_weight_kg_per_tow"], "se_kg_per_tow": h["se_weight_kg_per_tow"],
        "fish_per_tow": h["mean_count_per_tow"], "se_fish_per_tow": h["se_count_per_tow"],
        "kg_per_fish": h["mean_weight_kg_per_tow"] / h["mean_count_per_tow"],
        "total_t_x1.2_to_1981": validation["ours"], "published_t": validation["published"],
        "bottom_temp_c": bt["mean_bottom_temp_c"], "se_bottom_temp_c": bt["se_bottom_temp_c"],
        "bottom_temp_tows_from_ctd": bt["n_from_ctd"],
    }).rename_axis("year")
    table.to_csv(OUT / "haddock_4x5y.csv", float_format="%.4g")

    # Numbers quoted in haddock_4x5y.md
    ok = h[h["complete"].astype(bool)]
    kg, fish = ok["mean_weight_kg_per_tow"].astype(float), ok["mean_count_per_tow"].astype(float)
    per_fish = kg / fish
    decade = (ok.index // 10) * 10
    print("kg/tow by decade:", kg.groupby(decade).mean().round(1).to_dict())
    print("fish/tow by decade:", fish.groupby(decade).mean().round(1).to_dict())
    print("kg/fish by decade:", per_fish.groupby(decade).mean().round(2).to_dict())
    print(f"highest kg/tow: {kg.idxmax()} ({kg.max():.1f}); lowest: {kg.idxmin()} ({kg.min():.1f})")
    print(f"highest fish/tow: {fish.idxmax()} ({fish.max():.1f}); kg/fish that year {per_fish[fish.idxmax()]:.2f}")
    share, tow = largest_tow_share(int(kg.idxmax()))
    print(f"{kg.idxmax()}: largest tow ({tow}) is {share:.0%} of the stratified mean; "
          f"CV {float(ok.loc[kg.idxmax(), 'se_weight_kg_per_tow']) / kg.max():.0%}")
    print(f"validation: {len(validation)} years, max |diff| {validation['diff_pct'].abs().max():.2f}% "
          f"({validation['diff_pct'].abs().idxmax()}); 2005 before fix {before_fix:+.1f}%")
    early = kg.loc[1970:1981]
    print(f"1970-81 mean kg/tow: {early.mean():.1f} unconverted, {early.mean() * 1.2:.1f} with Fanning x1.2")

    print("bottom temp, incomplete years:", bt.loc[~bt["complete"].astype(bool), ["n_sets_with_temp", "area_coverage"]]
          .astype(float).to_dict(orient="index"))
    temp = bt.loc[bt["complete"].astype(bool), "mean_bottom_temp_c"].astype(float)
    slope = np.polyfit(temp.index.to_numpy(float), temp.to_numpy(), 1)[0] * 10
    print(f"bottom temp: {temp.index.min()}-{temp.index.max()}, {len(temp)} complete years; "
          f"1970-1999 mean {temp.loc[:1999].mean():.2f}, 2010-{temp.index.max()} mean {temp.loc[2010:].mean():.2f}, "
          f"warmest {temp.idxmax()} ({temp.max():.2f}), linear trend {slope:+.2f} C/decade")
    print(f"wrote {sorted(p.name for p in OUT.iterdir())}")


if __name__ == "__main__":
    main()
