from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from habench.campaign.texts import DictTextSource, ParquetTextSource, default_snapshots_dir


def test_dict_source_is_exact_and_missing_is_none() -> None:
    src = DictTextSource({1: "  padded \n"}, {1: " pt \n"})
    assert src.submitted_text(1) == "  padded \n"
    assert src.pt_indication(1) == " pt \n"
    assert src.submitted_text(2) is None and src.pt_indication(2) is None


def _write(tmp_path: Path) -> Path:
    v2 = tmp_path / "v2"
    v2.mkdir()
    pq.write_table(pa.table({"id_medication": [1, 2, 3], "ds_text_submitted": ["  a \n", None, "c"],
                             "other": [0, 0, 0]}), v2 / "api_response.parquet")
    pq.write_table(pa.table({"id_medication": [1, 3], "ds_indication": [" pt ", "ç"]}),
                   v2 / "translate_eng_leaflet_section.parquet")
    return tmp_path


def test_parquet_source_exact_values(tmp_path: Path) -> None:
    src = ParquetTextSource(_write(tmp_path))
    assert src.submitted_text(1) == "  a \n"
    assert src.submitted_text(2) is None
    assert src.submitted_text(99) is None
    assert src.pt_indication(1) == " pt "
    assert src.pt_indication(3) == "ç"
    assert src.pt_indication(2) is None


def test_parquet_source_is_lazy(tmp_path: Path) -> None:
    src = ParquetTextSource(tmp_path)  # files do not exist: nothing is read at construction
    with pytest.raises(Exception):
        src.submitted_text(1)


def test_parquet_source_rejects_conflicting_duplicates(tmp_path: Path) -> None:
    v2 = tmp_path / "v2"
    v2.mkdir()
    pq.write_table(pa.table({"id_medication": [1, 1], "ds_text_submitted": ["a", "b"]}),
                   v2 / "api_response.parquet")
    with pytest.raises(ValueError):
        ParquetTextSource(tmp_path).submitted_text(1)


def test_default_snapshots_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HAB_DATA_DIR", "/x")
    assert default_snapshots_dir() == Path("/x/snapshots")
