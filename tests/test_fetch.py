"""fetch.py tests. Downloads use file:// URLs, so no network is needed."""
import json
import zipfile

import pytest

from maritimes_rv import cli, fetch

STRATA = {"features": [{"attributes": {"STRAT": "441", "AREA": 1000}}, {"attributes": {"STRAT": "440", "AREA": 924}}]}


def package(path, names):
    with zipfile.ZipFile(path, "w") as z:
        for name in names:
            z.writestr(name, "MISSION\nNED2024001\n")
    return path


def source_files(tmp_path, names=("SUMMER_2024_GSINF.csv", "SUMMER_2024_GSCAT.csv"), strata=STRATA):
    src = tmp_path / "src"
    src.mkdir(exist_ok=True)
    (src / "strata.json").write_text(json.dumps(strata))
    return package(src / "pkg.zip", names).as_uri(), (src / "strata.json").as_uri()


def test_fetch_downloads_unpacks_and_fingerprints(tmp_path):
    raw = tmp_path / "raw"
    prints = fetch.fetch(raw, *source_files(tmp_path))
    assert sorted(prints) == ["SUMMER_csv/SUMMER_2024_GSCAT.csv", "SUMMER_csv/SUMMER_2024_GSINF.csv",
                              "rest_strata_layer1.json"]
    assert (raw / "SUMMER_csv" / "SUMMER_2024_GSINF.csv").read_text() == "MISSION\nNED2024001\n"
    assert not list(raw.glob("*.part"))


def test_new_package_replaces_files_from_an_older_release(tmp_path):
    raw = tmp_path / "raw"
    old = package(tmp_path / "old.zip", ["SUMMER_2023_GSINF.csv"])
    fetch.extract_csv_package(old, raw / "SUMMER_csv")
    new = package(tmp_path / "new.zip", ["SUMMER_2024_GSINF.csv"])
    fetch.extract_csv_package(new, raw / "SUMMER_csv")
    assert [p.name for p in (raw / "SUMMER_csv").iterdir()] == ["SUMMER_2024_GSINF.csv"]


@pytest.mark.parametrize("name", ["../evil.csv", "/abs.csv", "sub/x.csv", "sub\\x.csv", ".."])
def test_unexpected_paths_in_the_package_are_rejected(tmp_path, name):
    dest = tmp_path / "raw" / "SUMMER_csv"
    dest.mkdir(parents=True)
    (dest / "keep.csv").write_text("x")
    with pytest.raises(ValueError, match="unexpected entry"):
        fetch.extract_csv_package(package(tmp_path / "bad.zip", [name]), dest)
    assert [p.name for p in dest.iterdir()] == ["keep.csv"]  # existing data untouched


def test_strata_query_error_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="no features"):
        fetch.fetch(tmp_path / "raw", *source_files(tmp_path, strata={"error": {"code": 400}}))


def test_fingerprint_ignores_json_formatting_but_not_content(tmp_path):
    raw = tmp_path / "raw"
    fetch.fetch(raw, *source_files(tmp_path))
    before = fetch.fingerprint(raw)

    strata_file = raw / "rest_strata_layer1.json"
    reordered = {"features": list(reversed(STRATA["features"]))}
    strata_file.write_text(json.dumps(reordered, indent=4))
    assert fetch.fingerprint(raw) == before

    changed = json.loads(json.dumps(STRATA))
    changed["features"][0]["attributes"]["AREA"] = 1001
    strata_file.write_text(json.dumps(changed))
    after = fetch.fingerprint(raw)
    assert after["rest_strata_layer1.json"] != before["rest_strata_layer1.json"]
    assert after["SUMMER_csv/SUMMER_2024_GSINF.csv"] == before["SUMMER_csv/SUMMER_2024_GSINF.csv"]


def test_compare_fingerprints_lists_added_removed_and_changed_files():
    old = {"a.csv": "1", "b.csv": "2", "c.csv": "3"}
    new = {"a.csv": "1", "b.csv": "9", "d.csv": "4"}
    assert fetch.compare_fingerprints(old, new) == ["added d.csv", "removed c.csv", "changed b.csv"]
    assert fetch.compare_fingerprints(old, dict(old)) == []


def test_sources_compare_exit_status(tmp_path, capsys):
    raw = tmp_path / "raw"
    current = fetch.fetch(raw, *source_files(tmp_path))
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
