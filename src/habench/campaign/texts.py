"""Input texts for open (dev/cal) groups: V2 submitted ACM text and Portuguese indication, byte-exact."""

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Protocol

import pyarrow.parquet as pq


class TextSource(Protocol):
    def submitted_text(self, med: int) -> str | None:
        """Exact V2 ``ds_text_submitted`` (never stripped or normalized)."""
        ...

    def pt_indication(self, med: int) -> str | None:
        """Exact Portuguese ``ds_indication`` of hd_translate_eng_leaflet_section."""
        ...


class DictTextSource:
    def __init__(self, submitted: Mapping[int, str | None], pt: Mapping[int, str | None]) -> None:
        self._submitted = submitted
        self._pt = pt

    def submitted_text(self, med: int) -> str | None:
        return self._submitted.get(med)

    def pt_indication(self, med: int) -> str | None:
        return self._pt.get(med)


def default_snapshots_dir() -> Path:
    return Path(os.environ.get("HAB_DATA_DIR", "/home/vinicius/hab-data")) / "snapshots"


class ParquetTextSource:
    """Reads only the requested medication ids from the V2 snapshot parquet files, lazily, with a cache."""

    def __init__(self, snapshots_dir: Path) -> None:
        self._submitted_path = snapshots_dir / "v2" / "hd_int_med_disease_api_response.parquet"
        self._pt_path = snapshots_dir / "v2" / "hd_translate_eng_leaflet_section.parquet"
        self._cache: dict[tuple[str, int], str | None] = {}

    def submitted_text(self, med: int) -> str | None:
        return self._get("submitted", self._submitted_path, "ds_text_submitted", med)

    def pt_indication(self, med: int) -> str | None:
        return self._get("pt", self._pt_path, "ds_indication", med)

    def _get(self, kind: str, path: Path, column: str, med: int) -> str | None:
        key = (kind, med)
        if key not in self._cache:
            table = pq.read_table(path, columns=["id_medication", column],
                                  filters=[("id_medication", "=", med)])
            values = set(table.column(column).to_pylist())
            if len(values) > 1:
                raise ValueError(f"{path.name}: medication {med} has {len(values)} distinct {column} values")
            self._cache[key] = next(iter(values), None)
        return self._cache[key]
