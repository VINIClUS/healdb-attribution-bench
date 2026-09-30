"""Parquet snapshots of the HealDB dump tables, with a per-snapshot manifest.json."""

from __future__ import annotations

import hashlib
import itertools
import json
import os
import re
import sys
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from habench.data import dumps

DATA_DIR = Path(os.environ.get("HAB_DATA_DIR", "/home/vinicius/hab-data"))

SNAPSHOT_TABLES: dict[str, tuple[str, ...]] = {
    "v1": (
        "hd_int_med_disease_api_response",
        "hd_translate_eng_leaflet_section",
        "hd_medication",
        "hd_icd_group",
        "hd_icd_category",
        "hd_icd_subcategory",
        "hd_int_med_disease_entity",
        "hd_int_med_disease_trait",
        "hd_medication_disease",
        "hd_medication_disease_extend",
    ),
    "v2": (
        "hd_int_med_disease_api_response",
        "hd_translate_eng_leaflet_section",
        "hd_icd_group",
        "hd_icd_category",
        "hd_icd_subcategory",
        "hd_int_med_disease_entity_icd",
        "hd_int_med_disease_entity_trait",
        "hd_int_med_disease_cutoff_audit",
        "hd_medication_disease",
    ),
    "g0327": ("hd_int_med_disease_api_response",),
}
SNAPSHOT_SOURCE = {"v1": "V1", "v2": "V2", "g0327": "G0327"}

API_COLUMN = "ds_api_response"
SHA_COLUMN = "ds_api_response_sha256"
BATCH_ROWS = 20_000

_TYPE = re.compile(r"\s+`[^`]+` ([a-zA-Z]+)")
_INT_TYPES = {"int", "bigint", "tinyint", "smallint", "mediumint"}
_FLOAT_TYPES = {"float", "double", "decimal"}


def snapshot_path(snap: str, table: str) -> Path:
    return DATA_DIR / "snapshots" / snap / f"{table}.parquet"


def _manifest_path(snap: str) -> Path:
    return DATA_DIR / "snapshots" / snap / "manifest.json"


def manifest(snap: str) -> dict:
    p = _manifest_path(snap)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def _sha256_bytes_of_file(p: Path) -> str:
    with open(p, "rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def _arrow_types(file: Path) -> tuple[list[str], list[pa.DataType]]:
    names, types = [], []
    for line in dumps.create_table_lines(file):
        m = _TYPE.match(line)
        kind = m.group(1).lower() if m else ""
        names.append(dumps._COLUMN.match(line).group(1))  # type: ignore[union-attr]
        if kind in _INT_TYPES:
            types.append(pa.int64())
        elif kind in _FLOAT_TYPES:
            types.append(pa.float64())
        else:
            types.append(pa.string())
    return names, types


def _sha_of_text(s: str | None) -> str | None:
    return None if s is None else hashlib.sha256(s.encode("utf-8", "surrogateescape")).hexdigest()


def _write_table(src: Path, table: str, dest: Path) -> tuple[int, list[str]]:
    names, types = _arrow_types(src)
    with_sha = API_COLUMN in names
    api_idx = names.index(API_COLUMN) if with_sha else -1
    if with_sha:
        names = [*names, SHA_COLUMN]
        types = [*types, pa.string()]
    schema = pa.schema(list(zip(names, types)))
    n_src = len(names) - (1 if with_sha else 0)
    tmp = dest.with_name(dest.name + ".tmp")
    total = 0
    it = dumps.rows("", table, src)
    with pq.ParquetWriter(tmp, schema, compression="zstd", store_schema=False) as writer:
        while batch := list(itertools.islice(it, BATCH_ROWS)):
            cols: list[list] = [[] for _ in names]
            for row in batch:
                if len(row) != n_src:
                    raise ValueError(f"{table}: row has {len(row)} values, expected {n_src}")
                for j, v in enumerate(row):
                    if types[j] == pa.float64() and type(v) is int:
                        v = float(v)
                    cols[j].append(v)
                if with_sha:
                    cols[-1].append(_sha_of_text(row[api_idx]))
            writer.write_batch(pa.RecordBatch.from_arrays(
                [pa.array(c, type=t) for c, t in zip(cols, types)], schema=schema))
            total += len(batch)
    os.replace(tmp, dest)
    return total, names


def build_snapshot(snap: str, tables: Iterable[str] | None = None, *, force: bool = False) -> dict:
    """Write Parquet files for ``tables`` (default: all of the snapshot) and update manifest.json."""
    label = SNAPSHOT_SOURCE[snap]
    wanted = tuple(tables) if tables is not None else SNAPSHOT_TABLES[snap]
    out_dir = snapshot_path(snap, "x").parent
    out_dir.mkdir(parents=True, exist_ok=True)
    man = manifest(snap)
    for table in wanted:
        if table not in SNAPSHOT_TABLES[snap]:
            raise ValueError(f"{table} is not part of snapshot {snap}")
        src = dumps.path(label, table)
        src_sha = _sha256_bytes_of_file(src)
        dest = snapshot_path(snap, table)
        entry = man.get(table)
        if not force and entry and entry["source_sha256"] == src_sha and dest.exists():
            continue
        rows, cols = _write_table(src, table, dest)
        man[table] = {
            "source_file": str(src.resolve()),
            "source_sha256": src_sha,
            "source_bytes": src.stat().st_size,
            "rows": rows,
            "columns": cols,
            "snapshot_sha256": _sha256_bytes_of_file(dest),
            "built_at": datetime.now(UTC).isoformat(timespec="seconds"),
        }
        mp = _manifest_path(snap)
        tmp = mp.with_name(mp.name + ".tmp")
        tmp.write_text(json.dumps(man, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, mp)
    return man


def load_table(snap: str, table: str, columns: list[str] | None = None) -> pa.Table:
    return pq.read_table(snapshot_path(snap, table), columns=columns)


def load_records(snap: str, table: str, columns: list[str] | None = None) -> list[dict]:
    return load_table(snap, table, columns).to_pylist()


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[0] != "build" or argv[1] not in (*SNAPSHOT_TABLES, "all"):
        print("usage: python -m habench.data.store build [v1|v2|g0327|all]", file=sys.stderr)
        return 2
    for snap in SNAPSHOT_TABLES if argv[1] == "all" else [argv[1]]:
        man = build_snapshot(snap)
        print(snap, {t: e["rows"] for t, e in man.items()})
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
