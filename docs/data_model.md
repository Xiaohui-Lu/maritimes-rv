# Data model and methods

The cleaned tables, the indices built from them, and how they were validated. Problems in the raw data are described in `data_notes.md`; the DFO practice these choices follow is summarised in section 6. Written 2026-10-21.

## 1. Decisions

| # | Question | Decision | Reason |
|---|---|---|---|
| 1 | Spatial scope | Core strata 440–495 only | The CSV has no other strata; DFO's Mar.stratisfy also defaults to 440–495 |
| 2 | Incomplete years (2018, 2021, 2022) | Compute coverage per region × year; flag incomplete region-years instead of deleting them; downstream use excludes them by default | In those years 4X was fully surveyed and 4V/4W was not. DFO keeps them for 4X5Y stocks, drops them for stocks that include 4V/4W, and does not impute |
| 3 | Vessel and gear conversion factors | Off by default. Fanning (1985) factors, as DFO's code applies them, are in a reference table and can be switched on; outputs carry the gear and vessels used | DFO applies these factors to only a few species and considers the cod factor unreliable. Converting by default would suggest every species had been corrected |
| 4 | Bottom temperature gaps (2005, 2021–2023) | Fill a tow's missing reading from the CTD cast made at the same station (CIOOS Atlantic ERDDAP), matched by id or by position and time; keep the survey's own reading where it exists, and record the source | The cast at each station reproduces the survey's own reading within 0.1 °C for 99% of tows (`data_notes.md` 3.14). Casts from other places or days disagree by degrees, so they are never used |
| 5 | Zeros in TOTNO and TOTWGT | A TOTNO of 0 becomes missing; a TOTWGT of 0 is kept and flagged | TOTNO = 0 means "not counted". TOTWGT = 0 mostly means a catch under 0.5 kg recorded before 2000; making it missing would drop real small catches (`data_notes.md` 3.3) |

## 2. Layout

```
data/raw/                      downloaded files (survey package, strata, ctd/<year>.csv), never modified, not in git
src/maritimes_rv/reference/    hand-curated reference tables shipped with the package, each row with its source
data/clean/                    cleaned tables: one Parquet and one CSV per table, plus manifest.json; not in git
data/products/                 indices and bottom temperature, plus manifest.json; not in git
dist/                          a data release package (maritimes-rv release); not in git
site/                          the website and its JSON API (maritimes-rv site); not in git
```

`maritimes-rv fetch` fills `data/raw/`. `maritimes-rv sources` prints a content fingerprint of those files; the monthly release workflow compares it with the latest release to decide whether to publish a new one.

```
missions (mission)
   └─< sets (mission, setno) >── strata (stratum)
         └─< catch (mission, setno, species_code) >── species (species_code)
```

`manifest.json` records the SHA-256, size and modification date of every source file and the row count of every output table. DFO updates the dataset in place, so files with the same name may change; the manifest shows which version of the data produced a result.

## 3. Cleaned tables

Types are Arrow type names. Any column may be null unless it is part of the primary key (PK).

### 3.1 `missions`: one row per survey trip (94 rows)

| Column | Type | Source | Notes |
|---|---|---|---|
| mission | string | MISSION | PK, e.g. `NED2016016` |
| year | int16 | YEAR | |
| season | string | SEASON | Always `SUMMER` for now; kept so other surveys can be added |
| vessel_code | string | VESEL | A/H/N/S/T |
| vessel_name | string | `reference/vessels.csv` | Inferred from the MISSION prefix; the reference table records the confidence |
| cruise_no | int16 | CRUNO | |

### 3.2 `sets`: one row per tow (9,437 rows)

| Column | Type | Source | Notes |
|---|---|---|---|
| mission | string | MISSION | PK, part 1 |
| setno | int16 | SETNO | PK, part 2 |
| year | int16 | SDATE | Redundant, for convenient filtering |
| start_datetime_local | timestamp (no time zone) | SDATE + TIME | Local time; the source does not state the time zone |
| stratum | string | STRAT | Text, not integer, because codes such as `5Z1` exist |
| start_lat, start_lon | float64 | SLAT, SLONG | Decimal degrees |
| end_lat, end_lon | float64 | ELAT, ELONG | Missing for every tow before 1990 |
| duration_min | int16 | DUR | |
| distance_nmi | float64 | DIST | Nautical miles |
| speed_kn | float64 | SPEED | Knots; kept as recorded, suspect values flagged |
| depth_m | float64 | DEPTH | Metres; 46% missing |
| surface_temp_c | float64 | SURF_TEMP | |
| bottom_temp_c | float64 | BOTT_TEMP | Missing for every tow after 2020 |
| bottom_salinity_psu | float64 | BOTT_SAL | The dictionary's unit is wrong; values are PSU |
| gear | string | GEARDESC | `Western IIA trawl` or `Yankee #36 otter trawl` |
| vessel_code | string | missions | Redundant, to avoid a join in analysis |
| ctd_profile_id | string | computed | The CTD cast made at this station (see `ctd`); null if none was found |
| ctd_match | string | computed | `id` (the cast's id names this tow) or `position` (within 2 km and 2 hours of the tow's end) |
| ctd_distance_km | float64 | computed | Distance from the tow's end position to the cast |
| ctd_bottom_temp_c | float64 | ctd | Bottom temperature from that cast |
| bottom_temp_merged_c | float64 | computed | `bottom_temp_c` where recorded, else `ctd_bottom_temp_c` |
| bottom_temp_source | string | computed | `survey` or `ctd`: where `bottom_temp_merged_c` comes from |
| qc_ctd_temp_mismatch | bool | computed | Survey and same-station CTD readings differ by more than 0.5 °C (6 tows) |
| qc_speed_inconsistent | bool | computed | Recorded SPEED differs from DIST / (DUR / 60) by more than 1 kn (6 tows) |
| qc_speed_implausible | bool | computed | DIST / (DUR / 60) outside 2–5 kn (45 tows, 34 of them in the 1970s) |
| qc_depth_outside_stratum | bool | computed | Depth, converted to fathoms, more than 10 fathoms outside the stratum's band (18 tows) |
| qc_comparative_fishing | bool | computed | Vessel-comparison tows (16: 7 in HAM1981060, 9 in TEL2005605); left out of the index, see 4.1 |

The thresholds were chosen from the data:

- **Speed inconsistent.** SPEED is almost always DIST / DUR: 99% of tows agree within 0.04 kn. A gap above 1 kn means one of the values was recorded wrongly.
- **Speed implausible.** Standard tows run at about 3.5 kn. A consistency check alone misses tows where DIST and SPEED are both too high, such as ATC1973212 set 27 at 7.1 kn. The flagged tows cluster in the 1970s because distances were less precise then (`data_notes.md` 3.12), not because individual tows went wrong.
- **Depth tolerance of 10 fathoms.** Stratum bands are 50–100 fathoms wide, and tows near a boundary are naturally a little outside. 56 tows are more than 5 fathoms outside; 18 are more than 10.
- **Comparative fishing.** In a year with more than one vessel, a mission of the minority vessel is flagged when at least half its tows start within 3 nmi of a tow by the main vessel. Time is not used: the comparative tows are 0.7–2.7 nmi from the main vessel's tows but 3–9 days later. In 1991 the two vessels split the survey area and their nearest tows are 21–224 nmi apart, so nothing is flagged. By chance, a point falls within 3 nmi of some tow about 11% of the time; requiring half a mission's tows makes a false flag practically impossible.

Missing values never raise a flag. For example, a tow with no depth has `qc_depth_outside_stratum = False`.

### 3.3 `catch`: one row per tow and species caught (139,465 rows)

Only species that were caught are stored (sparse). Zeros are added at analysis time, for the tows that analysis uses (section 4.1).

| Column | Type | Source | Notes |
|---|---|---|---|
| mission | string | MISSION | PK |
| setno | int16 | SETNO | PK |
| species_code | int32 | SPEC | PK |
| weight_kg_std | float64 | TOTWGT | Weight per standard 1.75 nmi tow, kg. **Already standardised: do not rescale by distance** |
| count_std | float64 | TOTNO | Count per standard tow; fractional because standardised. Source zeros become missing |
| qc_weight_zero | bool | computed | Source TOTWGT is 0 with a count; mostly below the weighing precision |

The two entirely empty source rows (SPEC, TOTWGT and TOTNO all NA) are dropped. They are placeholders for two empty tows; those tows remain in `sets`, so zero-filling gives them zeros.

### 3.4 `species`: one row per species code (649 rows)

| Column | Type | Source | Notes |
|---|---|---|---|
| species_code | int32 | CODE | PK |
| scientific_name | string | SCI_NAME | |
| common_name | string | COMM | English common name; 32% missing |
| is_taxon | bool | computed | True when a scientific name exists; False for stones, garbage, "unidentified per set" and similar |

### 3.5 `strata`: one row per stratum (72 rows, from REST)

| Column | Type | Source | Notes |
|---|---|---|---|
| stratum | string | STRAT | PK |
| depth_min_fm | int16 | DMIN | Fathoms; the unit is in the name because the source does not give one |
| depth_max_fm | int16 | DMAX | Fathoms |
| area_nmi2 | float64 | AREA | Square nautical miles |
| area_km2 | float64 | computed | area_nmi2 × 3.429904 |
| is_core | bool | computed | True for 440–495 |
| area_group | string | computed | `4VW` for 440–466, `4X5Y` for 470–495, otherwise null; the groupings DFO uses for stock assessments |

The source's DEPTH column (nominal depth) has no documented unit and is not used, so it is dropped.

### 3.6 Reference tables (`src/maritimes_rv/reference/`, hand-curated)

They live inside the package rather than under `data/` so that an installed package can find them (read with `importlib.resources`).

- `vessels.csv`: vessel_code, mission_prefix, vessel_name, confidence, source. The integrity checks confirm that every mission's prefix matches its vessel code.
- `conversion_factors.csv`: species_code, vessel_codes (semicolon-separated), factor, source. A factor multiplies both the count and the weight of matching catches.

### 3.7 Integrity checks (the build fails if any fails)

Unlike the `qc_` flags, these problems mean the tables themselves cannot be trusted, so the build stops:

- no primary key is missing or duplicated, in any table;
- every foreign key resolves: sets → missions, sets → strata, catch → sets, catch → species;
- every mission's MISSION prefix matches its vessel code in `vessels.csv`;
- every `sets.ctd_profile_id` exists in `ctd` (a null value refers to nothing).

### 3.8 `ctd`: one row per summer CTD profile (6,226 rows for 1996–2023)

The deepest sample of each downward profile, from DFO BIO's survey CTD data on CIOOS Atlantic ERDDAP. The count can grow as BIO adds data.

| Column | Type | Source | Notes |
|---|---|---|---|
| profile_id | string | id | PK; usually names the cruise and set, e.g. `CTD_NED2016016_249_…` |
| cruise | string | cruise_number | Not always the trawl mission (`data_notes.md` 3.14) |
| station | string | station | |
| time_utc | timestamp | time | UTC |
| lat, lon | float64 | latitude, longitude | |
| depth_m | float64 | depth | Depth of the deepest sample |
| bottom_temp_c | float64 | TEMPS901, else TEMPPR01, else TEMPS601 | ITS-90 where available; the scales differ by less than 0.01 °C |
| bottom_salinity_psu | float64 | PSALST01, else PSLTZZ01 | |
| temp_flag | int8 | QTEMP_01 | BIO quality flag; casts flagged 2, 3, 4 or 9 are not matched |

How tows are matched to casts, and why it can be trusted, is in `data_notes.md` 3.14 and `temperature.py`.

## 4. Outputs and method

Command: `maritimes-rv index [--convert] [--species CODE ...]`. It reads `data/clean/` and writes `data/products/`: `index` and `bottom_temp` as Parquet and CSV, plus a manifest recording the parameters and the checksum of the cleaned tables' manifest.

### 4.1 Method

**The idea behind a stratified mean.** The survey area is divided into strata by depth and region, and tows are placed at random within each stratum. Each stratum's mean catch estimates its density; weighting those means by stratum area gives the mean for the whole region. Large strata are therefore not diluted by small ones, whatever the number of tows in each.

For stratum h with area A_h, n_h tows, mean catch ȳ_h and standard error se_h = s_h / √n_h:

- **Stratified mean** = Σ A_h·ȳ_h / Σ A_h, over the strata sampled that year.
- **Standard error** = √(Σ A_h²·se_h²) / Σ A_h, **over strata with n_h ≥ 2 only**. A stratum with one tow has no variance estimate; as in DFO's code, it is left out and the weights are renormalised over the remaining strata.
- **Trawlable total** = Σ (A_h / area swept by one standard tow) × ȳ_h. One standard tow sweeps 1.75 nmi × 41 ft ≈ 0.01181 square nautical miles. The total assumes the net catches every fish in its path (catchability = 1), so it is a relative index, not an estimate of stock size.
- **Zero-filling.** Tows where the species was not caught count as 0.
- **Comparative-fishing tows are excluded** (`qc_comparative_fishing`). This is not a quality judgement: they repeat stations the main vessel already fished and are not part of the stratified random design, so including them double-counts those stations. It is the only `qc_` flag excluded by default; the others are informational.

There are three fixed regions: `core` (440–495, 48 strata), `4VW` (440–466, 27 strata) and `4X5Y` (470–495, 21 strata).

### 4.2 Comparison with DFO's RVTransmogrifier

The formulas come from RVTransmogrifier's `stratify_simple()`, `calcYearSummary()`, `calcTotalMean()` and `calcTotalSE_stratified()`, and from `st_err()` in Mar.utils. Deliberate differences:

| Item | DFO | maritimes-rv | Reason |
|---|---|---|---|
| Missing TOTNO / TOTWGT | treated as 0 | excluded from that metric; counted in `n_count_missing` / `n_weight_missing` | Not counted is not zero (decision 5). The main fish species have almost no missing values, so results are identical; for species never counted, such as sponges, DFO's rule would produce a count index of zeros |
| SE when every stratum has a single tow | 0 | missing | The variance is unknown |
| Net width | gear-specific: Western IIA 41 ft, Yankee #36 35 ft | 41 ft for all years | As in Fanning (1985) and Mar.stratisfy; totals are then a constant multiple of the per-tow mean and show the same trend. Only the absolute 1970–81 totals differ (by 41/35 = 1.17) |
| nmi² → km² | 3.4299 (rounded) | 3.429904 | Totals differ by about one part in a million |
| Conversion factors | the internal GSCONVERSIONS table, converting every vessel to the newest Cartier/Cabot equivalent | the public Fanning factors only, converting to Needler equivalent; off by default | Decision 3 |

### 4.3 `index`: one row per region × year × species

By default every species with `is_taxon` is included: about 100,000 rows.

| Column | Notes |
|---|---|
| region, year, species_code | key |
| n_sets, n_strata_sampled, n_strata_total | tows in the region that year, strata sampled, strata in the region |
| area_coverage | area of the strata sampled / area of the region |
| complete | area_coverage ≥ 0.9. Observed coverage is always either ≥ 0.99 or ≤ 0.55, so any threshold in between gives the same result |
| gears, vessels | gear and vessel codes used that year |
| conversion_applied | True when `--convert` is on and the year includes a vessel with a factor for that species |
| mean_count_per_tow, se_count_per_tow | stratified mean count per standard tow and its SE |
| mean_weight_kg_per_tow, se_weight_kg_per_tow | stratified mean weight per standard tow (kg) and its SE |
| total_count, se_total_count | trawlable total count |
| total_weight_t, se_total_weight_t | trawlable total weight (tonnes) |
| n_count_missing, n_weight_missing | tows where the species was caught but not counted / not weighed |

A region-year with no tows at all (for example 4VW in 2021) is kept, with missing index values, so the year series never silently skips a year.

### 4.4 `bottom_temp`: one row per region × year

Columns: region, year, n_sets_with_temp, n_from_ctd, n_strata_sampled, n_strata_total, area_coverage, complete, mean_bottom_temp_c, se_bottom_temp_c.

The method is the same, applied to `bottom_temp_merged_c`: the survey's own reading where it exists, else the same-station CTD cast's. Coverage is computed from the tows with a reading, and `n_from_ctd` counts how many readings came from CTD casts. Years still without readings (2021) have n_sets_with_temp = 0 and complete = False. 2023 in 4X5Y reaches 88% of the area and stays incomplete.

2018 shows why the coverage flag is needed. Only 4X was surveyed that year, and the core region's mean bottom temperature comes out at 9.45 °C, more than 2 °C above the neighbouring years. The cause is not warming but the fact that only the warmer 4X was sampled.

### 4.5 Validation

1. **Hand-computed unit tests** (`tests/test_index.py`). They cover the stratified mean, SE, single-tow strata, totals, coverage, missing values, conversion factors, comparative-fishing tows and bottom temperature. Each expected value is worked out in the comments.
2. **A line-by-line port of DFO's code** (`validation/rvtransmogrifier_port.py`). `stratify_simple()` and `calcYearSummary()` are translated into a deliberately naive loop, including the "missing as 0" rule, that shares no code with `index.py`. It is compared on 864 rows (8 species × 2 regions × 54 years):
   - On the 824 rows without missing values, the largest relative difference is 1.4 × 10⁻¹⁵ for the mean and SE (floating-point precision) and 1.1 × 10⁻⁶ for totals (from DFO's rounded 3.4299).
   - The other 40 rows differ only because of the missing-value rule (34 sponge rows, 4 silver hake, 2 witch flounder), as expected.
3. **Published DFO indices** (`validation/compare_published.py`); see 4.6.
4. **CTD bottom temperatures against the survey's own** (`tests/test_pipeline.py`, `tests/test_temperature.py`). Where both exist, the same-station cast agrees within 0.1 °C for 99% of tows. Matching by position is confirmed independently by the cast ids (`data_notes.md` 3.14).

### 4.6 Comparison with published DFO indices

The published tables are transcribed in `validation/published/`, each with its source and transcription notes in the file header.

| Source | Series | Years | Years within 1% |
|---|---|---|---|
| Stone & Hansen 2015, Res. Doc. 2015/022, Table 9 | 4X5Y haddock total biomass (t), ×1.2 applied to 1970–81 | 1970–2014 | **45 / 45** (largest difference 0.8%) |
| Stobo et al. 1997, Res. Doc. 97/105 | 4X winter flounder, American plaice, yellowtail flounder: count and weight per tow | 1970–1997 | 57–79%; median ratio 0.997–1.000 |
| same | SEs of the above (bootstrap in the source) | 1970–1997 | 79–100% within 5% |
| Trippel & Brown 1993/94, Res. Doc. 93/60, 94/67 | 4VWX pollock count per tow | 1970–1993 | 75% |

**The haddock comparison exposed a data problem.** The first comparison was 40% too high in 2005: 61,121 t against 43,522 t published. The public data includes tows from the 2005 Needler–Teleost comparative fishing experiment, in which the Teleost re-fished stations the Needler had already fished, and it has no tow-type column to mark them. Without those tows the result is 43,492 t, a difference of 0.07%. The `qc_comparative_fishing` rule was added as a result, and it also found the 1981 Lady Hammond comparison tows. The comparison is now a regression test (`tests/test_published.py`).

**Likely causes of the remaining differences (inferred, not individually verified):**

- **Flatfish.** The differences cluster in 1970, 1971, 1976, 1978, 1979 and 1996. In those years the source's ratio of total abundance to mean count per tow is low, which suggests some strata were not sampled or not included at the time. In the current data 4X is fully covered in those years, so tows were probably added to the database after 1997.
- **Standard errors.** The source uses a bootstrap and this project an analytic formula; differences of a few percent are expected.
- **Pollock.** The source's TOTAL is a sum of numbers at age (length frequencies × age-length key), not the catch table's TOTNO, so exact agreement is not expected. The large differences in 1972, 1973 and 1980 are unexplained.

**Conclusion.** From 1982 on, the median relative difference from the published values is 0.07%. For 1970–81 it is 0.66%, concentrated in a few years; the most likely cause is revisions to those years' data after publication.

## 5. Open items and possible extensions

- **Stratum polygons are not used.** Checking whether each tow falls inside its stratum would need geographic dependencies such as shapely, and the depth check already catches miscoded strata.
- **Custom regions:** any list of strata as a region.
- **Exclusion options:** recomputing indices with tows excluded by other `qc_` flags.
- **Confidence-interval columns.** For now they are ±1.96 × SE.
- **A bottom temperature for 2021.** The CTD data has casts that year (HUD2021019), but the open trawl data has only two tows to attach them to. A temperature index built from the casts themselves would need stratum polygons to place each cast in a stratum.
- **Model-based indices**, which adjust for changes in distribution.

## 6. DFO practice: research summary

Researched 2026-10-21 from DFO's public code and CSAS publications.

- **DFO's public R tools.** The Maritimes organisation on GitHub has RVTransmogrifier (the current tool, still updated in October 2026), Mar.stratisfy (an R port of the older STRANAL program), Mar.datawrangling and Mar.utils.
  - Tow selection: only TYPE = 1 (valid tows) in summer (May–August). The public CSV has no TYPE column and is presumably already filtered.
  - All of them zero-fill at calculation time.
  - Mar.stratisfy standardises catches by 1.75 / DIST itself.
  - Net widths: Western IIA 41 ft, Yankee #36 35 ft.
- **Stratified mean and variance.** Mean and SE s/√n per stratum, missing when n < 2. Overall mean = Σ(A_h/A)·ȳ_h, SE = √Σ(A_h/A)²·se_h². No finite-population correction.
- **Conversion factors.** Fanning, L.P. 1985, CAFSAC Res. Doc. 85/3. Applied by DFO to 1970–81 data:
  - haddock ×1.2;
  - American plaice, witch flounder, yellowtail flounder and winter flounder ×0.8;
  - silver hake ×2.3 (from the silver hake assessment).

  The cod factor is considered unreliable, and the 4X5Y cod assessment does not use data before 1983. Teleost–Needler factors were re-estimated in 2025 (Res. Doc. 2025/026); some are length-based, and this data has no lengths.
- **2018, 2021 and 2022.** Vessel mechanical problems left most of 4V/4W unsurveyed, while 4X5Yb was fully surveyed. DFO drops these years for stocks that include 4V/4W and does not impute (Science Response 2025/017). The Needler broke down in 2021 and was decommissioned in February 2023.
- **Bottom temperature.** CIOOS Atlantic ERDDAP dataset `bio_maritimes_region_ecosystem_survey_ctd` (1996–2026, Open Government Licence). The 2023 profiles are filed under CAR2023011, not TEL2023010, the mission in the catch data; their positions and times show they are the casts made at the TEL2023010 stations. They are now used to fill gaps (decision 4).
- **Newer data.** There is no official CSV newer than SUMMER_2023. DFO's RVSurveyData repository on GitHub has data to 2025, but from 2021 the survey uses new vessels and NEST gear, which need the 2025 conversion factors (Res. Doc. 2025/025), and it is not a formal open-data release.

Main sources:
- Fanning 1985: https://waves-vagues.dfo-mpo.gc.ca/library-bibliotheque/75575.pdf
- Science Response 2025/017: https://waves-vagues.dfo-mpo.gc.ca/library-bibliotheque/4129130x.pdf
- 4X5Y haddock, Res. Doc. 2015/022: https://waves-vagues.dfo-mpo.gc.ca/library-bibliotheque/359710.pdf
- 4X5Y cod, Res. Doc. 2022/006: https://waves-vagues.dfo-mpo.gc.ca/library-bibliotheque/41058203.pdf
- Res. Doc. 2025/026: https://waves-vagues.dfo-mpo.gc.ca/library-bibliotheque/41299139.pdf
- ERDDAP: https://erddap.cioosatlantic.ca/erddap/tabledap/bio_maritimes_region_ecosystem_survey_ctd.html
- DFO code: https://github.com/Maritimes
