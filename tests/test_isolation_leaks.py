from __future__ import annotations

import gzip
import zipfile
from pathlib import Path

from habench.views.isolation import scan_leaks

TERMS = ["family_N", "Seed"]


def test_clean_tree(tmp_path: Path):
    (tmp_path / "f_001.json").write_text('{"x": 1}')
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "f_002.json").write_text("nothing here")
    assert scan_leaks(tmp_path, TERMS) == []


def test_file_name(tmp_path: Path):
    (tmp_path / "run_family_N.json").write_text("{}")
    assert scan_leaks(tmp_path, TERMS) == [("run_family_N.json", "family_N")]


def test_directory_name(tmp_path: Path):
    (tmp_path / "SEED_dir").mkdir()
    assert scan_leaks(tmp_path, TERMS) == [("SEED_dir", "Seed")]


def test_content_case_insensitive(tmp_path: Path):
    (tmp_path / "a.json").write_text('{"FAMILY_n": 1}')
    assert scan_leaks(tmp_path, TERMS) == [("a.json", "family_N")]


def test_gzip_content(tmp_path: Path):
    (tmp_path / "a.gz").write_bytes(gzip.compress(b"the Seed is 7"))
    assert scan_leaks(tmp_path, TERMS) == [("a.gz", "Seed")]


def test_zip_member_name_and_content(tmp_path: Path):
    with zipfile.ZipFile(tmp_path / "v.zip", "w") as zf:
        zf.writestr("inner/family_n.txt", "harmless")
        zf.writestr("inner/b.txt", "contains seed value")
        zf.writestr("inner/c.txt", "clean")
    hits = scan_leaks(tmp_path, TERMS)
    assert ("v.zip!inner/family_n.txt", "family_N") in hits
    assert ("v.zip!inner/b.txt", "Seed") in hits
    assert all("c.txt" not in label for label, _ in hits)


def test_gzip_inside_zip(tmp_path: Path):
    with zipfile.ZipFile(tmp_path / "v.zip", "w") as zf:
        zf.writestr("m.gz", gzip.compress(b"family_N"))
    assert scan_leaks(tmp_path, TERMS) == [("v.zip!m.gz", "family_N")]
