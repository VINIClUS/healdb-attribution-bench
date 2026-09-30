"""Offline side of the Docker replay of 405a10c (protocol §5.3).

`scripts/replay/driver.py` (inside the container) exports `entity`, `trait` and `md` as TSV; this module reads
those files, compares them with the V1 snapshots and writes `repro/replay_manifest.json` from the logs.

TSV format (one physical line per row, header first): tab-separated, NULL is the two characters `\\N`, strings
escape backslash, tab, newline and carriage return as `\\\\`, `\\t`, `\\n`, `\\r`, floats are written with `repr`.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Callable
from pathlib import Path

from habench.pipeline.tables_v1 import ENTITY_COLUMNS, MD_COLUMNS, compare_rows

REPLAY_DIR = Path("/home/vinicius/hab-data/replay")
REPO_ROOT = Path(__file__).parents[3]
NULL = "\\N"

TRAIT_COLUMNS = ("id_medication", "cd_icd_full", "nm_trait", "vl_trait_score")
_ENTITY_KINDS = ("int", "str", "str", "float", "str", "float", "str", "int", "int", "str", "str")
_TRAIT_KINDS = ("int", "str", "str", "float")
_MD_KINDS = ("int", "int", "str", "int", "int", "int", "float", "float", "int", "str", "float")

# table label -> (V1 snapshot table, columns, kinds, primary key)
TABLES: dict[str, tuple[str, tuple[str, ...], dict[str, str], tuple[str, ...]]] = {
    "entity": (
        "hd_int_med_disease_entity", ENTITY_COLUMNS, dict(zip(ENTITY_COLUMNS, _ENTITY_KINDS, strict=True)),
        ("id_medication", "cd_icd_full"),
    ),
    "trait": (
        "hd_int_med_disease_trait", TRAIT_COLUMNS, dict(zip(TRAIT_COLUMNS, _TRAIT_KINDS, strict=True)),
        ("id_medication", "cd_icd_full", "nm_trait"),
    ),
    "md": (
        "hd_medication_disease", MD_COLUMNS, dict(zip(MD_COLUMNS, _MD_KINDS, strict=True)), ("id_med_disease",),
    ),
}
MD_KINDS = TABLES["md"][2]

# Known differences between the replay and the V1 dump, by explicit (table, primary key, column).
# F1 §2.4 / inventory: after MySQL re-parses the JSON the double for medication 560, code C49.9, is one ULP
# away from the dump's value (Python parsing the dump text reproduces V1 exactly). Whitelisting requires
# the replay and snapshot values to be exactly adjacent doubles; anything else stays unexplained.
KNOWN_DIFFERENCES: dict[tuple[str, tuple, str], str] = {
    ("entity", (560, "C49.9"), "vl_score"): "1 ULP after the MySQL reload of the JSON response (F1)",
}


# ---- TSV -----------------------------------------------------------------------------------------------

_ESCAPES = {"\\": "\\", "t": "\t", "n": "\n", "r": "\r"}


def format_cell(v) -> str:
    if v is None:
        return NULL
    if isinstance(v, bool):
        return str(int(v))
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return repr(v)
    if isinstance(v, (bytes, bytearray)):
        v = bytes(v).decode("utf-8")
    return v.replace("\\", "\\\\").replace("\t", "\\t").replace("\n", "\\n").replace("\r", "\\r")


def _unescape(s: str) -> str:
    return re.sub(r"\\(.)", lambda m: _ESCAPES[m.group(1)], s, flags=re.S)


def parse_cell(raw: str, kind: str):
    if raw == NULL:
        return None
    if kind == "int":
        return int(raw)
    if kind == "float":
        return float(raw)
    return _unescape(raw)


def read_tsv(path: Path, kinds: dict[str, str]) -> list[dict]:
    rows: list[dict] = []
    with open(path, encoding="utf-8", newline="\n") as fh:
        header = fh.readline().rstrip("\n").split("\t")
        if header != list(kinds):
            raise ValueError(f"{path}: header {header} differs from the expected columns {list(kinds)}")
        for line in fh:
            cells = line.rstrip("\n").split("\t")
            if len(cells) != len(header):
                raise ValueError(f"{path}: row with {len(cells)} cells, expected {len(header)}")
            rows.append({c: parse_cell(x, kinds[c]) for c, x in zip(header, cells, strict=True)})
    return rows


def write_tsv(path: Path, columns: tuple[str, ...], rows: list[dict]) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\t".join(columns) + "\n")
        for r in rows:
            fh.write("\t".join(format_cell(r[c]) for c in columns) + "\n")


# ---- comparison ------------------------------------------------------------------------------------------


def _one_ulp_apart(a, b) -> bool:
    return (
        isinstance(a, float) and isinstance(b, float) and math.isfinite(a) and math.isfinite(b)
        and (b == math.nextafter(a, math.inf) or b == math.nextafter(a, -math.inf))
    )


def _snapshot_rows(table: str) -> list[dict]:
    from habench.data.store import load_records

    snap, columns, _, _ = TABLES[table]
    return load_records("v1", snap, list(columns))


def compare(out_dir: Path | str, theirs: dict[str, list[dict]] | None = None) -> dict:
    """Replay TSVs (`entity.tsv`, `trait.tsv`, `md.tsv` in `out_dir`) against the V1 snapshots.

    `theirs` maps table label -> snapshot rows (default: loaded from the V1 Parquet snapshot). Equality is exact
    (type-sensitive; the entity JSON column is parsed). Differences listed in KNOWN_DIFFERENCES are moved to
    `whitelisted` only when both values are adjacent doubles; every other difference is `unexplained`.
    """
    out_dir = Path(out_dir)
    tables: dict[str, dict] = {}
    whitelisted: list[dict] = []
    used: set[tuple] = set()
    for label, (_, columns, kinds, key) in TABLES.items():
        ours = read_tsv(out_dir / f"{label}.tsv", kinds)
        snap = theirs[label] if theirs is not None else _snapshot_rows(label)
        cmp = compare_rows(ours, snap, key, ("ds_attributes",) if label == "entity" else ())
        unexplained = []
        for kk, col, a, b in cmp["differ"]:
            wl = (label, kk, col)
            if wl in KNOWN_DIFFERENCES and _one_ulp_apart(a, b):
                used.add(wl)
                whitelisted.append({
                    "table": label, "key": list(kk), "column": col, "replay": a, "snapshot": b,
                    "replay_repr": repr(a), "snapshot_repr": repr(b), "note": KNOWN_DIFFERENCES[wl],
                })
            else:
                unexplained.append({"key": list(kk), "column": col, "replay": a, "snapshot": b})
        tables[label] = {
            "n_replay": cmp["n_ours"],
            "n_snapshot": cmp["n_theirs"],
            "n_only_replay": len(cmp["only_ours"]),
            "n_only_snapshot": len(cmp["only_theirs"]),
            "only_replay": [list(k) for k in cmp["only_ours"][:5]],
            "only_snapshot": [list(k) for k in cmp["only_theirs"][:5]],
            "n_unexplained": len(unexplained),
            "unexplained": unexplained[:20],
            "order_equal": cmp["order_equal"],
        }
    unused = [
        {"table": t, "key": list(k), "column": c} for (t, k, c) in KNOWN_DIFFERENCES if (t, k, c) not in used
    ]
    equal = all(
        t["n_unexplained"] == 0 and t["n_only_replay"] == 0 and t["n_only_snapshot"] == 0 and t["order_equal"]
        for t in tables.values()
    )
    return {"equal": equal, "tables": tables, "whitelisted": whitelisted, "whitelist_unused": unused}


# ---- logs and manifest -----------------------------------------------------------------------------------

_END = re.compile(r"\] end (\S+): ([0-9.]+)s \| (.*)$")
_TOTAL = re.compile(r"\] total ([0-9.]+)s")
_OP = re.compile(r"\] OPERATOR ACTION: (.*)$")
_VERSIONS = re.compile(r"\] versions: (.*)$")
_LOAD = re.compile(r"^load (\S+) (\S+) (OK|ERR.*) (\d+)s$")


def _lines(path: Path) -> list[str]:
    if not path.is_file():
        return []
    return path.read_text(encoding="utf-8", errors="replace").splitlines()


def parse_driver_log(lines: list[str]) -> dict:
    timings: dict[str, float] = {}
    counts: dict[str, dict[str, int]] = {}
    operator_actions: list[str] = []
    versions = None
    total = None
    errors = 0
    for line in lines:
        if line.startswith("Error"):
            errors += 1
        if m := _END.search(line):
            timings[m.group(1)] = float(m.group(2))
            counts[m.group(1)] = {k: int(v) for k, v in (p.split("=") for p in m.group(3).split())}
        elif m := _TOTAL.search(line):
            total = float(m.group(1))
        elif m := _OP.search(line):
            operator_actions.append(m.group(1))
        elif m := _VERSIONS.search(line):
            versions = m.group(1)
    return {
        "timings_s": timings, "row_counts_after_stage": counts, "operator_actions": operator_actions,
        "versions": versions, "total_s": total, "historical_error_lines": errors,
    }


def _parse_loads(lines: list[str]) -> list[dict]:
    out = []
    for line in lines:
        if m := _LOAD.match(line):
            out.append({"schema": m.group(1), "table": m.group(2), "status": m.group(3), "seconds": int(m.group(4))})
    return out


def _parse_blobs(lines: list[str]) -> list[dict]:
    out = []
    for line in lines:
        parts = line.split()
        if len(parts) == 3 and parts[0] in ("blob_ok", "commit"):
            out.append({"kind": parts[0], "id": parts[1], "path": parts[2]})
    return out


def write_replay_manifest(
    log_dir: Path | str,
    out_path: Path | str = "repro/replay_manifest.json",
    *,
    export_dir: Path | str | None = None,
    compare_result: dict | None = None,
    xval_result: list[dict] | None = None,
    compare_fn: Callable[[Path], dict] = compare,
) -> dict:
    """Record the Docker replay from its logs (run by the lead after the main session executed Docker).

    Log directory files (written by scripts/replay/*.sh and driver.py): images.txt, pip_freeze.txt, blobs.txt,
    commands.log, up.log, replay_405a10c.log; `export_dir` (default `<log_dir>/../export`) holds the TSVs and
    export_meta.json. Missing files are recorded as empty, never invented.
    """
    log_dir = Path(log_dir)
    export_dir = Path(export_dir) if export_dir is not None else log_dir.parent / "export"
    out = Path(out_path)
    if not out.is_absolute():
        out = REPO_ROOT / out
    meta_path = export_dir / "export_meta.json"
    export_meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else None
    if compare_result is None and all((export_dir / f"{t}.tsv").is_file() for t in TABLES):
        compare_result = compare_fn(export_dir)
    manifest = {
        "images": _lines(log_dir / "images.txt"),
        "pip_freeze": _lines(log_dir / "pip_freeze.txt"),
        "blobs": _parse_blobs(_lines(log_dir / "blobs.txt")),
        "commands": _lines(log_dir / "commands.log"),
        "loads": _parse_loads(_lines(log_dir / "up.log")),
        "replay": parse_driver_log(_lines(log_dir / "replay_405a10c.log")),
        "export": export_meta,
        "compare": compare_result,
        "xval": xval_result,
        "log_dir": str(log_dir),
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return manifest
