"""Download the source files from DFO's open-data services into data/raw, and fingerprint them."""
import hashlib
import json
import shutil
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections.abc import Callable
from pathlib import Path, PurePosixPath

from . import raw

CSV_PACKAGE_URL = ("https://api-proxy.edh-cde.dfo-mpo.gc.ca/catalogue/records/"
                   "1366e1f1-e2c8-4905-89ae-e10f1be0a164/attachments/SUMMER_csv.zip")
STRATA_URL = ("https://egisp.dfo-mpo.gc.ca/arcgis/rest/services/open_data_donnees_ouvertes/"
              "maritimes_summer_research_vessel_survey_en/MapServer/1/query"
              "?where=1%3D1&outFields=STRAT,DMIN,DMAX,AREA,DEPTH&returnGeometry=false&orderByFields=STRAT&f=json")
CSV_PACKAGE_FILE = "SUMMER_csv.zip"

# CTD profiles from the same survey, published by DFO's Bedford Institute of Oceanography on CIOOS Atlantic
CTD_URL = "https://erddap.cioosatlantic.ca/erddap/tabledap/bio_maritimes_region_ecosystem_survey_ctd.csv"
CTD_VARIABLES = ("id,cruise_number,station,time,latitude,longitude,depth,"
                 "TEMPS901,TEMPS601,TEMPPR01,QTEMP_01,PSALST01,PSLTZZ01")
CTD_FIRST_YEAR = 1996  # the dataset starts in 1996


def ctd_url(year: int) -> str:
    """The deepest sample of every downward CTD profile in one summer; ERDDAP's orderByMax does it server-side."""
    constraints = [f"time>={year}-05-15", f"time<{year}-09-15", 'profile_direction="downward"', 'orderByMax("id,depth")']
    return f"{CTD_URL}?{CTD_VARIABLES}&" + "&".join(urllib.parse.quote(c, safe="") for c in constraints)


def download(url: str, dest: Path, attempts: int = 3) -> None:
    """Download to a temporary file first, so a failed download never leaves a partial file in place."""
    request = urllib.request.Request(url, headers={"User-Agent": "maritimes-rv"})
    partial = dest.with_name(dest.name + ".part")
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(request, timeout=120) as response, partial.open("wb") as out:
                shutil.copyfileobj(response, out)
            partial.replace(dest)
            return
        except urllib.error.HTTPError as error:
            partial.unlink(missing_ok=True)
            if error.code < 500 or attempt == attempts:  # a client error will not go away by retrying
                raise
            time.sleep(2 ** attempt)
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            partial.unlink(missing_ok=True)
            if attempt == attempts:
                raise
            time.sleep(2 ** attempt)


def extract_csv_package(archive: Path, dest_dir: Path) -> None:
    """Unpack the CSV package, replacing dest_dir so files from an older release never linger."""
    with zipfile.ZipFile(archive) as z:
        for name in z.namelist():
            path = PurePosixPath(name)
            # The package is flat; anything else (sub-folders, "..", absolute paths) is not what we expect.
            if len(path.parts) != 1 or path.name in ("", ".", "..") or "\\" in name:
                raise ValueError(f"unexpected entry in {archive.name}: {name!r}")
        dest_dir.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=".csv-", dir=dest_dir.parent))
        z.extractall(staging)
    if dest_dir.exists():
        shutil.rmtree(dest_dir)
    staging.rename(dest_dir)


def check_strata(path: Path) -> None:
    # The ESRI service reports query errors with HTTP 200 and an "error" member in the JSON.
    payload = json.loads(path.read_text(encoding="utf-8"))
    if "error" in payload or not payload.get("features"):
        raise ValueError(f"strata query returned no features: {str(payload)[:200]}")


def fetch_ctd(raw_dir: Path, years, url_for: Callable[[int], str] = ctd_url) -> None:
    """One file per summer into raw/ctd, replacing the folder so files from an older download never linger."""
    staging = Path(tempfile.mkdtemp(prefix=".ctd-", dir=raw_dir))
    try:
        for year in years:
            try:
                download(url_for(year), staging / f"{year}.csv")
            except urllib.error.HTTPError as error:
                if error.code != 404:  # ERDDAP answers 404 when a query matches no profiles
                    raise
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    if (raw_dir / raw.CTD_DIR).exists():
        shutil.rmtree(raw_dir / raw.CTD_DIR)
    staging.rename(raw_dir / raw.CTD_DIR)


def fetch(raw_dir: Path, csv_url: str = CSV_PACKAGE_URL, strata_url: str = STRATA_URL,
          ctd_url_for: Callable[[int], str] = ctd_url) -> dict[str, str]:
    raw_dir.mkdir(parents=True, exist_ok=True)
    download(csv_url, raw_dir / CSV_PACKAGE_FILE)
    extract_csv_package(raw_dir / CSV_PACKAGE_FILE, raw_dir / raw.CSV_DIR)
    download(strata_url, raw_dir / raw.STRATA_FILE)
    check_strata(raw_dir / raw.STRATA_FILE)
    years = raw.read_csv_table(raw_dir, "GSMISSIONS")["YEAR"]
    fetch_ctd(raw_dir, range(max(CTD_FIRST_YEAR, int(years.min())), int(years.max()) + 1), ctd_url_for)
    return fingerprint(raw_dir)


def fingerprint(raw_dir: Path) -> dict[str, str]:
    """SHA-256 of each source file's content, unchanged by re-downloading unchanged data.

    Every file in the CSV package counts, so a new release (renamed files, a filled-in GSDET) shows up.
    The strata response and the CTD files are hashed as their sorted contents, so a change in how a
    service formats or orders its output does not count as a change in the data.
    """
    prints = {f"{raw.CSV_DIR}/{p.name}": _sha256(p.read_bytes())
              for p in sorted((raw_dir / raw.CSV_DIR).iterdir()) if p.is_file()}
    payload = json.loads((raw_dir / raw.STRATA_FILE).read_text(encoding="utf-8"))
    strata = sorted((f["attributes"] for f in payload["features"]), key=lambda a: str(a.get("STRAT")))
    prints[raw.STRATA_FILE] = _sha256(json.dumps(strata, sort_keys=True).encode())
    for path in raw.ctd_files(raw_dir):
        table = raw.read_ctd_file(path)
        canonical = table.sort_values(list(table.columns), ignore_index=True).to_csv(index=False, lineterminator="\n")
        prints[f"{raw.CTD_DIR}/{path.name}"] = _sha256(canonical.encode())
    return prints


def compare_fingerprints(old: dict[str, str], new: dict[str, str]) -> list[str]:
    """Differences between two fingerprints, compared by content rather than by file bytes."""
    return ([f"added {name}" for name in sorted(new.keys() - old.keys())]
            + [f"removed {name}" for name in sorted(old.keys() - new.keys())]
            + [f"changed {name}" for name in sorted(old.keys() & new.keys()) if old[name] != new[name]])


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
