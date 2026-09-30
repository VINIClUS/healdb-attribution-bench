"""Blind annotation sheets: export for annotators and parse their answers."""

from __future__ import annotations

import csv
import hashlib
import hmac
import random
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

SHEET_COLUMNS = ("blind_id", "annotator", "document_ref", "text", "codes", "evidence", "notes")
_CODE_RE = re.compile(r"^[A-Z][0-9]{2}[0-9A-Z]?$")


@dataclass(frozen=True)
class SheetItem:
    unit_id: str
    document_ref: str  # reference document fixed by version (e.g. leaflet sha256/version)
    text: str  # Portuguese indication section to annotate


@dataclass(frozen=True)
class Annotation:
    unit_id: str
    annotator: str
    codes: frozenset[str]
    evidence: str
    notes: str


def blind_ids(unit_ids: Iterable[str], key: bytes) -> dict[str, str]:
    return {u: "u" + hmac.new(key, u.encode("utf-8"), hashlib.sha256).hexdigest()[:12] for u in unit_ids}


def export_sheet(items: Iterable[SheetItem], annotator: str, path: str | Path, key: bytes, seed: int) -> None:
    """Write the sheet with shuffled rows; only blind ids, annotator, document and text are exposed."""
    items = list(items)
    ids = blind_ids((i.unit_id for i in items), key)
    order = sorted(items, key=lambda i: ids[i.unit_id])
    random.Random(seed).shuffle(order)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, quoting=csv.QUOTE_ALL)
        w.writerow(SHEET_COLUMNS)
        for i in order:
            w.writerow([ids[i.unit_id], annotator, i.document_ref, i.text, "", "", ""])


def category(code: str) -> str:
    return code[:3]


def normalize_code(raw: str) -> str:
    code = raw.strip().upper().replace(".", "")
    if not _CODE_RE.match(code):
        raise ValueError(f"malformed ICD-10 code: {raw!r}")
    return code


def read_annotations(path: str | Path, key_map: Mapping[str, str]) -> dict[str, Annotation]:
    """Parse a filled sheet; `key_map` maps blind ids back to unit ids."""
    out: dict[str, Annotation] = {}
    with open(path, encoding="utf-8", newline="") as fh:
        for row_no, row in enumerate(csv.DictReader(fh), start=2):  # row 1 is the header
            blind = row["blind_id"]
            where = f"row {row_no} ({blind})"
            if blind not in key_map:
                raise ValueError(f"{where}: unknown blind id")
            unit_id = key_map[blind]
            if unit_id in out:
                raise ValueError(f"{where}: duplicate unit")
            try:
                codes = frozenset(normalize_code(c) for c in row["codes"].split(";") if c.strip())
            except ValueError as exc:
                raise ValueError(f"{where}: {exc}") from None
            out[unit_id] = Annotation(unit_id, row["annotator"], codes, row["evidence"], row["notes"])
    return out
