"""F2 §1: are the V1 (20250711) dump files byte-identical to the 0605 OpenSource ones, except the stamp line?

The normalization removes only lines starting with "-- Dump completed on" (F2 §8, layer 1).
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from habench.data.dumps import DUMPS_DIR, SOURCES

STAMP = b"-- Dump completed on"
OUT_PATH = Path(__file__).parents[3] / "docs" / "estudo_a" / "dumps_v1_0605.json"


def digests(path: Path) -> tuple[str, str]:
    """(raw sha256, sha256 without the stamp lines)."""
    raw, norm = hashlib.sha256(), hashlib.sha256()
    with open(path, "rb") as f:
        for line in f:
            raw.update(line)
            if not line.startswith(STAMP):
                norm.update(line)
    return raw.hexdigest(), norm.hexdigest()


def compare(a: str = "V1", b: str = "O0605") -> dict:
    da, db = DUMPS_DIR / SOURCES[a], DUMPS_DIR / SOURCES[b]
    fa = {p.name for p in da.glob("*.sql")}
    fb = {p.name for p in db.glob("*.sql")}
    tables = {}
    for name in sorted(fa & fb):
        ra, na = digests(da / name)
        rb, nb = digests(db / name)
        tables[name] = {"raw_equal": ra == rb, "normalized_equal": na == nb, "normalized_sha256": na}
    return {
        "compared": f"{a} vs {b}: sha256 of each .sql, raw and without lines starting with '-- Dump completed on'",
        "only_in_" + a: sorted(fa - fb),
        "only_in_" + b: sorted(fb - fa),
        "files_in_common": len(tables),
        "normalized_equal": sum(t["normalized_equal"] for t in tables.values()),
        "raw_equal": sum(t["raw_equal"] for t in tables.values()),
        "tables": tables,
    }


def main(argv: list[str]) -> int:
    res = compare()
    OUT_PATH.write_text(json.dumps(res, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print({k: v for k, v in res.items() if k != "tables"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
