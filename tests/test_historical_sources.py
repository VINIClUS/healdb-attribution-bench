from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from habench.historical import sources


def test_hash_file_matches_hashlib(tmp_path: Path) -> None:
    path = tmp_path / "a.bin"
    data = b"abc" * 1_000_000
    path.write_bytes(data)
    assert sources.hash_file(path, "sha256") == hashlib.sha256(data).hexdigest()
    assert sources.hash_file(path, "md5") == hashlib.md5(data).hexdigest()  # noqa: S324


def test_dumps_json_is_sorted_and_deterministic() -> None:
    a = sources.dumps_json({"b": 1, "a": {"y": 2, "x": 3}})
    b = sources.dumps_json({"a": {"x": 3, "y": 2}, "b": 1})
    assert a == b
    assert a.endswith("\n")
    assert list(json.loads(a)) == ["a", "b"]


def test_reports_section_verifies_and_reports_missing(tmp_path: Path) -> None:
    (tmp_path / "f.md").write_text("hello", encoding="utf-8")
    good = hashlib.sha256(b"hello").hexdigest()
    sums = tmp_path / "SHA256SUMS"
    sums.write_text(f"{good}  f.md\n{'0' * 64}  gone.md\n{'1' * 64}  {tmp_path}/f.md\n")
    out = sources.reports_section(sums)
    assert out["f.md"]["match"] is True
    assert out["gone.md"] == {
        "sha256_listed": "0" * 64,
        "exists": False,
        "sha256_local": None,
        "match": None,
    }
    assert out[f"{tmp_path}/f.md"]["match"] is False


def test_redu_section_local_null_and_md5(tmp_path: Path) -> None:
    def entry(file_id: int, name: str, md5: str) -> dict:
        return {
            "version": 1,
            "dataFile": {"id": file_id, "filename": name, "filesize": 3, "md5": md5},
        }

    good = hashlib.md5(b"abc").hexdigest()  # noqa: S324
    versions = {
        "data": [
            {"versionNumber": 2, "files": [entry(1, "a.txt", good), entry(2, "b.txt", "x")]},
            {"versionNumber": 1, "files": [entry(1, "a.txt", good)]},
        ]
    }
    vpath = tmp_path / "v.json"
    vpath.write_text(json.dumps(versions), encoding="utf-8")
    (tmp_path / "1__a.txt").write_bytes(b"abc")
    out = sources.redu_section(vpath, tmp_path)
    first, second = out["files"]
    assert first["dataset_versions"] == [1, 2]
    assert first["md5_match"] is True
    assert first["local"]["sha256"] == hashlib.sha256(b"abc").hexdigest()
    assert second["local"] is None and second["md5_match"] is False


def test_diff_reports_mismatches() -> None:
    assert sources._diff({"a": {"b": 1}}, {"a": {"b": 1}}) == []
    problems = sources._diff({"a": {"b": 1}, "c": 1}, {"a": {"b": 2}, "d": 1})
    assert len(problems) == 3


@pytest.mark.dumps
def test_committed_manifest_checks_clean() -> None:
    assert sources.check_manifest() == []


@pytest.mark.dumps
def test_redu_md5_recomputed_match_stated() -> None:
    manifest = json.loads(sources.MANIFEST_PATH.read_text(encoding="utf-8"))
    mismatches = [
        (f["dataverse_file_id"], f["name"], f["md5_stated"], f["local"])
        for f in manifest["redu"]["files"]
        if f["local"] is not None and not f["md5_match"]
    ]
    assert mismatches == []
