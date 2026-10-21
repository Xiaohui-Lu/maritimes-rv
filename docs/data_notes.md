# Raw data notes

What the public release of the DFO Maritimes summer RV survey contains, and the problems found in it. Every number can be reproduced with `uv run python scripts/profile_raw.py data/raw`. Written 2026-10-21 against the CSV package dated 2023-11-08.

## 1. Files

| File | Source | Contents |
|---|---|---|
| `SUMMER_csv.zip` | open.canada.ca CSV resource | Archive; same contents as `SUMMER_csv/` |
| `SUMMER_csv/SUMMER_2023_GSMISSIONS.csv` | archive | Survey trips, 94 rows |
| `SUMMER_csv/SUMMER_2023_GSINF.csv` | archive | Tows (sets), 9,437 rows |
| `SUMMER_csv/SUMMER_2023_GSCAT.csv` | archive | Catch by tow and species, 139,467 rows |
| `SUMMER_csv/SUMMER_2023_GSSPECIES.csv` | archive | Species codes, 649 rows |
| `SUMMER_csv/SUMMER_2023_GSDET.csv` | archive | **Empty**: header `""` only |
| `SUMMER_csv/DataDictionary_202008.xlsx` | archive | Data dictionary by table; more complete than the separate one |
| `DataDictionary_Summer.csv` | separate open.canada.ca resource | Describes only the two GIS tables |
| `rest_strata_layer1.json` | ESRI REST layer 1 (section 5) | Strata table: 72 strata with areas |
| `ctd/<year>.csv` | CIOOS Atlantic ERDDAP (section 3.14) | Deepest sample of each downward CTD profile, one file per summer from 1996 |

The files in the archive are dated 2023-11-08 and the data run to 2023.

## 2. Tables and relationships

```
GSMISSIONS (MISSION)
   └─< GSINF (MISSION, SETNO)              one row per tow: time, position, stratum, distance, temperature, salinity
         ├─< GSCAT (MISSION, SETNO, SPEC)  one row per tow and species caught: TOTWGT (kg), TOTNO
         │     └── GSSPECIES (CODE = SPEC)
         └── STRATA (STRAT)                from the REST service, not in the CSV package
```

Referential integrity holds throughout:

- every GSCAT tow exists in GSINF;
- every GSINF tow has at least one GSCAT row;
- missions match on both sides;
- no primary key is duplicated.

Field names differ between the CSV and GIS versions. The CSV uses `SDATE`, `DEPTH` and `GEARDESC`; the GIS version and `DataDictionary_Summer.csv` use `SDT`, `DEP` and `GRDESC`.

The CSVs were written by R, so missing values are the bare string `NA`. Read them with `na_values=["NA"]`.

## 3. Findings that affect the design

### 3.1 Catches are already standardised to a 1.75 nmi tow

The dictionary describes TOTWGT as "total weight of the catch in kg" and TOTNO as the "number of pieces", with no mention of standardisation. But:

- **Counts are fractional.** For tows not exactly 1.75 nmi long (123,363 rows), only 3.9% of TOTNO values are whole numbers, although a count of fish should be. When the distance is exactly 1.75 nmi, scaling changes nothing and the count stays whole.
- **Scaling back recovers whole numbers.** Multiplying by DIST / 1.75 turns 99.9% of counts back into whole numbers, and 98.9% of weights into whole grams.

So TOTWGT and TOTNO have already been converted to a standard 1.75 nmi tow as `raw × 1.75 / DIST`. **They must not be standardised by distance again.** Raw values can be recovered with the same formula.

### 3.2 Species not caught have no row

GSCAT only lists species that were caught. A missing tow-species row means zero caught, not missing data. Before computing an index, every tow × species combination must be filled in, with zeros for the missing ones. Without zero-filling, the mean only covers tows where the species was caught and is badly inflated.

### 3.3 Zero does not mean zero, and the two columns differ

No row has both values equal to 0.

**`TOTNO = 0` (4,491 rows, all with TOTWGT > 0) means "not counted".**

- All are from 1990 onward.
- They are mostly hard-to-count invertebrates: sponges, sea urchins, jellyfish, basket stars, hermit crabs, whelk eggs and brittle stars.
- Cleaning turns them into missing values.

**`TOTWGT = 0` (8,861 rows, all with TOTNO > 0) mostly means "too light to register".**

- 8,827 of them (99.6%) are from before 2000.
- In the 1970s and 1980s the smallest non-zero weight is 1 kg, so weights were recorded to the whole kilogram.
- Using each species' median weight per fish, the median expected weight of these rows is only 0.2 kg, so most are small catches rounded down to 0.
- About 23% have an expected weight above 0.5 kg (for example, 17 cod recorded as 0 kg). These look more like catches that were not weighed.

The handling is in `data_model.md`, decision 5.

### 3.4 Weighing precision changed over time

| Period | Smallest non-zero weight (scaled back to the actual tow distance) |
|---|---|
| 1970s–1980s | 1 kg |
| 1990s | about 1 g |
| 2000 onward | about 0.1 g |

Before 1990, biomass data for small species (light fish, small catches) are coarse, with many values of 0 or 1 kg. Their biomass indices are not directly comparable before and after 1990. Count indices are not affected.

### 3.5 Stratum areas are not in the CSV package, and depths are in fathoms

A stratified mean needs each stratum's area as its weight, but the CSV package has no strata table. It exists only in the FGDB and the ESRI REST service. It was downloaded from REST layer 1 as `rest_strata_layer1.json` (query in section 5).

- It has 72 strata, including all 48 that appear in the CSV (440–495).
- Those 48 strata cover 50,032 square nautical miles.
- **DMIN and DMAX are in fathoms, not metres.** The dictionary gives no unit. With tow depths converted to fathoms, 98.9% fall inside their stratum's depth band; read as metres, only 22.2% do. The bands are 0–50, 51–100 and 101–200 fathoms.

### 3.6 The CSV contains only the core strata 440–495

The REST strata table also lists 496–498, 501–505 and 558–560 (deep strata towards the Laurentian Channel) and 5Z1–5Z9 (Georges Bank). The dataset description says the survey has recently expanded into these areas, but the CSV package has no tows there.

REST layer 0 has some of them (for example, 32 extra tows in NED2016016), but REST has no catch table. The pipeline therefore covers only the 4VWX core strata 440–495.

### 3.7 Vessel and gear changes

| VESEL | MISSION prefix | Vessel (inferred from the prefix) | Years |
|---|---|---|---|
| A | ATC | CCGS A.T. Cameron | 1970–1981 |
| H | HAM | Lady Hammond | 1981, 1982, 1991 |
| N | NED | CCGS Alfred Needler | 1983–2021 |
| S | TEL | CCGS Teleost | 2004, 2005, 2007, 2018, 2022, 2023 |
| T | TEM | CCGS Wilfred Templeman | 2008 |

Gear: the Yankee #36 otter trawl was used in 1970–1981 and the Western IIA trawl from 1981 to 2023. Both appear in 1981.

Vessels and nets differ in catchability: the same amount of fish can give systematically different catches on another vessel or with another net. A time series that spans these changes is not directly comparable, and DFO adjusts for some of them with conversion factors (`data_model.md` section 6).

### 3.8 Years with incomplete coverage

| Year | Tows | Strata sampled (of 48) | Note |
|---|---|---|---|
| 2018 | 81 | 24 | about half the area |
| 2021 | 2 | 1 | survey essentially not carried out |
| 2022 | 131 | 28 | partial |

Every other year sampled at least 40 strata (most years all 48), with 110–243 tows per year.

23 stratum-years have only one tow. Their within-stratum variance cannot be estimated, because that needs at least two tows.

### 3.9 Gaps in bottom temperature

| Years | BOTT_TEMP missing |
|---|---|
| 1970–2019 | 1–13% per decade on average |
| 2020 | 21% |
| 2021–2023 | 100% |

Salinity and surface temperature are missing in the same pattern.

**2005 is also almost entirely missing.** This was hidden by the decade averages and found when plotting the series:

- NED2005034 has no readings in any of its 110 tows.
- NED2005027 has readings for only 21 of its 103 tows, none of them in 4X5Y.
- So 4X5Y has no bottom temperature in 2005, and the core region is covered for only 22% of its area.

In 1985, six 4X5Y strata have no readings, so coverage there is 75%.

The REST service has no temperatures for these years either, and it records missing values as 0 (section 3.10).

Most of these gaps can be filled from the CTD cast made at each station, which is published separately (section 3.14). That fills 2005, 2022 and most of 2023; 2021 stays empty.

### 3.10 REST layer 0 (tows) is not usable as is

- **Duplicated tows.** It has 18,871 rows, about twice the CSV: most tows appear twice, as two versions of the same tow. Between the versions, SDT sometimes differs by a day (probably a time-zone conversion) and DEP is rounded differently.
- **Missing temperatures are recorded as 0.** All 131 TEL2022010 tows have BOTT_TEMP = 0. Since 0 °C is a plausible bottom temperature, this would silently corrupt the data.
- **No catch table.**

The CSV package is therefore the main source, and only the strata table is taken from REST.

### 3.11 No length or age data

The dataset description mentions length frequencies, and age, sex, maturity and weight for a subset of fish. The Excel dictionary also lists the GSDET fields. But `GSDET.csv` in the archive is empty.

### 3.12 Early tow distances are imprecise

Tow speed computed as DIST / (DUR / 60):

| Period | Gear | Standard deviation | 5%–95% range |
|---|---|---|---|
| 1970–81 | Yankee #36 | 0.61 kn | 2.8–4.6 kn |
| 1982–89 | Western IIA | 0.24 kn | 3.2–3.8 kn |
| 1990s | Western IIA | 0.19 kn | 3.2–3.8 kn |
| 2010–23 | Western IIA | 0.10 kn | 3.36–3.64 kn |

In the 1970s DIST was recorded only to 0.1 nmi, and the spread is six times today's.

- **Effect on catches.** Catches are standardised by 1.75 / DIST, so a distance error carries straight into the standardised catch. A tow that covered 1.75 nmi but was recorded as 1.4 nmi has its catch overstated by 25%. The early data are noisier as a result.
- **Dictionary.** The dictionary says SPEED is "based on GPS", which cannot be true for the 1970s and applies only to recent years.

### 3.13 Comparative-fishing tows are mixed in

Found by comparing the haddock index with a published DFO table.

- **Which tows.** Nine tows in TEL2005605 (the 2005 Needler–Teleost comparative fishing experiment) and seven in HAM1981060 (the 1979–81 A.T. Cameron–Lady Hammond experiment; Fanning 1985). The second vessel returned 3–9 days later to stations the main vessel had already fished; its tows are 0.7–2.7 nmi from the main vessel's.
- **Why it matters.** The public data has no tow-type (TYPE) column, so these tows look like ordinary survey tows. Including them in a stratified mean double-counts those stations: 2005 4X5Y haddock biomass comes out 40% too high.
- **Handling.** They are flagged by the `qc_comparative_fishing` rule and left out of the index (`data_model.md` sections 3.2 and 4.6).

### 3.14 The CTD cast at each station, and the survey's time zone

DFO's Bedford Institute of Oceanography publishes the survey's CTD profiles separately, as "Maritimes Region Ecosystem Survey Rosette Vertical Profiles" on CIOOS Atlantic ERDDAP (`bio_maritimes_region_ecosystem_survey_ctd`, 1996 onward, Open Government Licence – Canada). `maritimes-rv fetch` downloads the deepest sample of each downward profile for every summer: 6,226 casts for 1996–2023.

**Where and when the cast is made.** Matched to the tows (below), a cast lies a median of 0.8 km from the tow's **end** position (3.8 km from its start) and about 15 minutes after the tow ends.

**The survey's local time is Atlantic Daylight Time (UTC−3).** The data dictionary does not say. Cast time (UTC) minus tow start (local) is a median of 3.74 hours:

- Under UTC−3, the cast follows the 30-minute tow by about 15 minutes, at the tow's end position. This is consistent.
- Under UTC−4 (Atlantic Standard Time), it would come 16 minutes before the tow started, while the ship was already at the end position. This is impossible.

**Matching a tow to its cast.**

1. **By id.** Profile ids name the cruise and set, e.g. `CTD_NED2016016_249_…`. A cast named for the tow is used if it is within 10 km and 12 hours of the tow's end; a few ids are mislabelled, one by 317 km.
2. **By position.** Otherwise the nearest cast within 2 km and 2 hours of the tow's end is used, unless that cast is named for another tow of the same cruise.

The id and the position agree independently: 99.8% of position matches within a cruise point to the cast named for that very set.

**Cruise numbers do not always match.** Some casts are filed under a different cruise from the trawl mission:

- 1997–2000: numeric cruise numbers, e.g. `98027` for NED1998027.
- 2005: casts for NED2005027 and NED2005034 tows are filed under the Teleost cruises TEL2005605 and TEL2005633.
- 2023: casts for the TEL2023010 tows are filed under CAR2023011 (Capt. Jacques Cartier).

Their position and timing fit the same-station pattern exactly, so position matching finds them.

**Validation.** Where a tow has both a survey bottom temperature and a matched cast, the two agree within 0.1 °C for 99.1% of id matches (n = 3,490) and 99.4% of position matches (n = 688). The survey's value evidently comes from this cast.

**Disagreements.** Six tows differ by more than 0.5 °C (up to 3.97 °C) even though the cast is their own; one of the two values must be wrong. They are flagged `qc_ctd_temp_mismatch`.

**Gaps filled.** The CTD reading fills 436 tows that have no survey bottom temperature: 145 in 2005, 125 in 2022, 154 in 2023 and 12 in other years. 2021 cannot be filled: the open trawl data has only two tows that year.

## 4. Minor issues

| Issue | Where | Handling |
|---|---|---|
| SPEED = 36.0 kn, clearly a data-entry error (should be about 3.4–3.6) | NED1997726 set 21 | flagged (`qc_speed_inconsistent`) |
| SPEED 6.3–7.1 kn, consistent with DIST/DUR, so DIST or DUR is probably wrong | ATC1973212 set 27 and 2 others | flagged (`qc_speed_implausible`) |
| 2 GSCAT rows entirely empty (SPEC, TOTWGT, TOTNO all NA), the only row for their tow | NED2017020 set 123, ATC1970175 set 19 | treated as empty tows; zero-filling handles them |
| 13 TOTWGT values missing (all 1974–1988), 195 TOTNO values missing (mostly species codes in the 2xxx range) | GSCAT | kept as missing |
| DEPTH was originally recorded in fathoms: 88.9% of values are whole multiples of 1.8288 | GSINF | noted; 46% missing, mostly in the 1990s and 2000s |
| ELAT/ELONG missing for every tow before 1990 | GSINF | only start positions are available before 1990 |
| DUR is 30 min for 91% of tows; about 800 tows are 20–29 min | GSINF | no effect, since catches are standardised by distance |
| 26 GSSPECIES rows have no scientific name: stones, garbage, "Nth unidentified per set" (9991–9999), etc. | GSSPECIES | `is_taxon = False`; excluded from biological analysis |
| The dictionary lists TSN (ITIS taxonomic serial number), but GSSPECIES has no such column | GSSPECIES | noted |
| The dictionary calls the scientific-name field SPEC; the column is SCI_NAME | Excel dictionary | noted |
| The dictionary gives BOTT_SAL units as "pounds per square unit"; they are PSU | both dictionaries | noted |
| The dataset title is misspelled "Martimes" | open.canada.ca | noted |

## 5. Reproducing the REST and ERDDAP queries

`maritimes-rv fetch` runs these queries (and downloads the CSV package) automatically. The CTD query for one summer is built by `fetch.ctd_url()`: the variables listed in `fetch.CTD_VARIABLES`, restricted to 15 May–15 September and `profile_direction="downward"`, with `orderByMax("id,depth")` so the server returns only the deepest sample of each profile.

REST service root:
`https://egisp.dfo-mpo.gc.ca/arcgis/rest/services/open_data_donnees_ouvertes/maritimes_summer_research_vessel_survey_en/MapServer`

- Layer 0: Maritimes Summer RV Survey (tow points)
- Layer 1: Maritimes RV Survey Strata (stratum polygons)

Query for `rest_strata_layer1.json` (attributes only, no geometry):
`.../MapServer/1/query?where=1%3D1&outFields=STRAT,DMIN,DMAX,AREA,DEPTH&returnGeometry=false&orderByFields=STRAT&f=json`
