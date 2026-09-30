import csv

import pytest

from habench.annotation.sheets import (
    SHEET_COLUMNS,
    SheetItem,
    blind_ids,
    category,
    export_sheet,
    normalize_code,
    read_annotations,
)

KEY = b"test-key"


def test_blind_ids():
    ids = blind_ids(["a", "b"], KEY)
    assert all(v.startswith("u") and len(v) == 13 for v in ids.values())
    assert ids["a"] != ids["b"]
    assert ids == blind_ids(["b", "a"], KEY)
    assert ids["a"] != blind_ids(["a"], b"other")["a"]


def _items():
    return [SheetItem(f"UNIT-SECRET-{i}", "leaflet-v1-sha", f"Indicado para a doença {i} (ação)") for i in range(8)]


def test_sheet_layout_and_no_leak(tmp_path):
    path = tmp_path / "sheet.csv"
    export_sheet(_items(), "ann1", path, KEY, seed=3)
    raw = path.read_bytes()
    for leaked in (b"UNIT-SECRET", b"stratum", b"group_id", b"weight", b"phase", b"double", b"single", b"pi1"):
        assert leaked not in raw
    assert "ação".encode() in raw
    with open(path, encoding="utf-8", newline="") as fh:
        rows = list(csv.reader(fh))
    assert tuple(rows[0]) == SHEET_COLUMNS == (
        "blind_id", "annotator", "document_ref", "text", "codes", "evidence", "notes"
    )
    assert len(rows) == 9
    assert all(r[4:] == ["", "", ""] and r[1] == "ann1" for r in rows[1:])
    assert raw.count(b'"') >= 9 * 7 * 2  # QUOTE_ALL


def test_shuffle_seeded(tmp_path):
    export_sheet(_items(), "a", tmp_path / "1.csv", KEY, seed=3)
    export_sheet(_items(), "a", tmp_path / "2.csv", KEY, seed=3)
    export_sheet(_items(), "a", tmp_path / "3.csv", KEY, seed=4)
    assert (tmp_path / "1.csv").read_bytes() == (tmp_path / "2.csv").read_bytes()
    assert (tmp_path / "1.csv").read_bytes() != (tmp_path / "3.csv").read_bytes()


def _filled(tmp_path, codes_by_row):
    path = tmp_path / "sheet.csv"
    export_sheet(_items()[:2], "ann1", path, KEY, seed=1)
    with open(path, encoding="utf-8", newline="") as fh:
        rows = list(csv.reader(fh))
    for row, codes in zip(rows[1:], codes_by_row):
        row[4], row[5], row[6] = codes, "trecho", "nota"
    with open(path, "w", encoding="utf-8", newline="") as fh:
        csv.writer(fh).writerows(rows)
    ids = blind_ids([i.unit_id for i in _items()[:2]], KEY)
    return path, {v: k for k, v in ids.items()}


def test_read_annotations_normalizes(tmp_path):
    path, key_map = _filled(tmp_path, [" j45.0 ; e11;;", ""])
    ann = read_annotations(path, key_map)
    codes = sorted(sorted(a.codes) for a in ann.values())
    assert codes == [[], ["E11", "J450"]]
    a = next(a for a in ann.values() if a.codes)
    assert (a.annotator, a.evidence, a.notes) == ("ann1", "trecho", "nota")
    assert category("J450") == "J45"


@pytest.mark.parametrize("bad", ["J4", "12A", "J45.00", "JJ5", "J45-1"])
def test_malformed_codes_name_row(tmp_path, bad):
    path, key_map = _filled(tmp_path, ["A00", bad])
    with pytest.raises(ValueError, match=r"row 3"):
        read_annotations(path, key_map)


def test_unknown_blind_id(tmp_path):
    path, key_map = _filled(tmp_path, ["A00", "B00"])
    with pytest.raises(ValueError, match="unknown blind id"):
        read_annotations(path, dict(list(key_map.items())[:1]))


def test_normalize_code():
    assert normalize_code(" a01.1 ") == "A011"
    assert normalize_code("k51") == "K51"
