"""fetch.py tests. Downloads use file:// URLs, so no network is needed."""
import json
import urllib.error
import zipfile

import pytest

from maritimes_rv import cli, fetch

STRATA = {"features": [{"attributes": {"STRAT": "441", "AREA": 1000}}, {"attributes": {"STRAT": "440", "AREA": 924}}]}
PACKAGE = {
    "SUMMER_2024_GSMISSIONS.csv": "MISSION,YEAR\nNED2024001,2024\n",
    "SUMMER_2024_GSINF.csv": "MISSION\nNED2024001\n",
    "SUMMER_2024_GSCAT.csv": "MISSION\nNED2024001\n",
}
CTD_HEADER = ("id,cruise_number,station,time,latitude,longitude,depth,TEMPS901,TEMPS601,TEMPPR01,QTEMP_01,PSALST01,PSLTZZ01\n"
              ",,,UTC,degrees_north,degrees_east,m,degC,degC,degC,,PSU,PSU\n")
CTD_ROWS = ["CTD_NED2024001_001_1_DN,NED2024001,S1,2024-07-01T12:00:00Z,44.0,-63.0,100.0,6.5,,6.5,1,33.0,33.0\n",
            "CTD_NED2024001_002_2_DN,NED2024001,S2,2024-07-01T15:00:00Z,44.1,-63.1,120.0,7.5,,7.5,1,33.5,33.5\n"]


def package(path, contents):
    with zipfile.ZipFile(path, "w") as z:
        for name, text in contents.items():
            z.writestr(name, text)
    return path


def sources(tmp_path, strata=STRATA, ctd_rows=CTD_ROWS):
    """Keyword arguments for fetch.fetch() that point at local files."""
    src = tmp_path / "src"
    src.mkdir(exist_ok=True)
    (src / "strata.json").write_text(json.dumps(strata))
    (src / "2024.csv").write_text(CTD_HEADER + "".join(ctd_rows))
    return {"csv_url": package(src / "pkg.zip", PACKAGE).as_uri(), "strata_url": (src / "strata.json").as_uri(),
            "ctd_url_for": lambda year: (src / f"{year}.csv").as_uri()}


def test_fetch_downloads_unpacks_and_fingerprints(tmp_path):
    raw = tmp_path / "raw"
    prints = fetch.fetch(raw, **sources(tmp_path))
    assert sorted(prints) == ["SUMMER_csv/SUMMER_2024_GSCAT.csv", "SUMMER_csv/SUMMER_2024_GSINF.csv",
                              "SUMMER_csv/SUMMER_2024_GSMISSIONS.csv", "ctd/2024.csv", "rest_strata_layer1.json"]
    assert (raw / "SUMMER_csv" / "SUMMER_2024_GSINF.csv").read_text() == "MISSION\nNED2024001\n"
    assert not list(raw.glob("*.part")) and not list(raw.glob(".ctd-*"))


def test_ctd_url_asks_erddap_for_the_deepest_downward_sample_of_one_summer():
    url = fetch.ctd_url(2022)
    assert url.startswith(fetch.CTD_URL + "?id,cruise_number,")
    for part in ("time%3E%3D2022-05-15", "time%3C2022-09-15", "profile_direction%3D%22downward%22",
                 "orderByMax%28%22id%2Cdepth%22%29"):
        assert part in url


def test_years_without_ctd_profiles_are_skipped(tmp_path, monkeypatch):
    def download(url, dest, attempts=3):
        if url.endswith("2021"):  # ERDDAP answers 404 when a query matches no profiles
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
        dest.write_text(CTD_HEADER)
    monkeypatch.setattr(fetch, "download", download)
    raw = tmp_path / "raw"
    raw.mkdir()
    fetch.fetch_ctd(raw, [2020, 2021, 2022], url_for=lambda year: f"https://example.test/{year}")
    assert sorted(p.name for p in (raw / "ctd").iterdir()) == ["2020.csv", "2022.csv"]


def test_ctd_server_error_keeps_the_previous_files(tmp_path, monkeypatch):
    raw = tmp_path / "raw"
    (raw / "ctd").mkdir(parents=True)
    (raw / "ctd" / "2020.csv").write_text("previous")

    def download(url, dest, attempts=3):
        raise urllib.error.HTTPError(url, 500, "Server Error", {}, None)
    monkeypatch.setattr(fetch, "download", download)
    with pytest.raises(urllib.error.HTTPError):
        fetch.fetch_ctd(raw, [2020], url_for=lambda year: "https://example.test")
    assert (raw / "ctd" / "2020.csv").read_text() == "previous"
    assert not list(raw.glob(".ctd-*"))


def test_new_package_replaces_files_from_an_older_release(tmp_path):
    raw = tmp_path / "raw"
    fetch.extract_csv_package(package(tmp_path / "old.zip", {"SUMMER_2023_GSINF.csv": "x"}), raw / "SUMMER_csv")
    fetch.extract_csv_package(package(tmp_path / "new.zip", {"SUMMER_2024_GSINF.csv": "x"}), raw / "SUMMER_csv")
    assert [p.name for p in (raw / "SUMMER_csv").iterdir()] == ["SUMMER_2024_GSINF.csv"]


@pytest.mark.parametrize("name", ["../evil.csv", "/abs.csv", "sub/x.csv", "sub\\x.csv", ".."])
def test_unexpected_paths_in_the_package_are_rejected(tmp_path, name):
    dest = tmp_path / "raw" / "SUMMER_csv"
    dest.mkdir(parents=True)
    (dest / "keep.csv").write_text("x")
    with pytest.raises(ValueError, match="unexpected entry"):
        fetch.extract_csv_package(package(tmp_path / "bad.zip", {name: "x"}), dest)
    assert [p.name for p in dest.iterdir()] == ["keep.csv"]  # existing data untouched


def test_strata_query_error_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="no features"):
        fetch.fetch(tmp_path / "raw", **sources(tmp_path, strata={"error": {"code": 400}}))


def test_fingerprint_ignores_formatting_and_order_but_not_content(tmp_path):
    raw = tmp_path / "raw"
    fetch.fetch(raw, **sources(tmp_path))
    before = fetch.fingerprint(raw)

    strata_file = raw / "rest_strata_layer1.json"
    strata_file.write_text(json.dumps({"features": list(reversed(STRATA["features"]))}, indent=4))
    ctd_file = raw / "ctd" / "2024.csv"
    ctd_file.write_bytes((CTD_HEADER + "".join(reversed(CTD_ROWS))).replace("\n", "\r\n").encode())
    assert fetch.fingerprint(raw) == before

    changed = json.loads(json.dumps(STRATA))
    changed["features"][0]["attributes"]["AREA"] = 1001
    strata_file.write_text(json.dumps(changed))
    ctd_file.write_text(CTD_HEADER + CTD_ROWS[0].replace(",6.5,", ",6.6,"))
    after = fetch.fingerprint(raw)
    assert after["rest_strata_layer1.json"] != before["rest_strata_layer1.json"]
    assert after["ctd/2024.csv"] != before["ctd/2024.csv"]
    assert after["SUMMER_csv/SUMMER_2024_GSINF.csv"] == before["SUMMER_csv/SUMMER_2024_GSINF.csv"]


def test_compare_fingerprints_lists_added_removed_and_changed_files():
    old = {"a.csv": "1", "b.csv": "2", "c.csv": "3"}
    new = {"a.csv": "1", "b.csv": "9", "d.csv": "4"}
    assert fetch.compare_fingerprints(old, new) == ["added d.csv", "removed c.csv", "changed b.csv"]
    assert fetch.compare_fingerprints(old, dict(old)) == []


def test_sources_compare_exit_status(tmp_path, capsys):
    raw = tmp_path / "raw"
    current = fetch.fetch(raw, **sources(tmp_path))
    saved = tmp_path / "saved.json"

    # Same content, different formatting and line endings: unchanged.
    saved.write_bytes(json.dumps(dict(reversed(current.items())), indent=4).replace("\n", "\r\n").encode())
    cli.main(["sources", "--raw", str(raw), "--compare", str(saved)])
    assert "unchanged" in capsys.readouterr().out

    saved.write_text(json.dumps({**current, "SUMMER_csv/SUMMER_2024_GSINF.csv": "old"}))
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["sources", "--raw", str(raw), "--compare", str(saved)])
    assert exit_info.value.code == 1
    assert "- changed SUMMER_csv/SUMMER_2024_GSINF.csv" in capsys.readouterr().out
