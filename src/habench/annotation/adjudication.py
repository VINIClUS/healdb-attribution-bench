"""Adjudication of disagreements between two annotators (run after agreement is computed)."""

from __future__ import annotations

import csv
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from habench.annotation.sheets import Annotation


class PendingAdjudication(Exception):
    def __init__(self, items: list[tuple[str, str]]) -> None:
        super().__init__(f"{len(items)} items need an adjudicator decision: {items[:10]}")
        self.items = items


@dataclass(frozen=True)
class AdjudicatedUnit:
    unit_id: str
    codes: frozenset[str]
    sources: dict[str, str]  # code -> "agreed" | "adjudicated" | "single"
    annotators: tuple[str, ...]


def pending_items(a: Mapping[str, Annotation], b: Mapping[str, Annotation]) -> list[tuple[str, str]]:
    """(unit, code) pairs annotated by exactly one coder on doubly annotated units. Codes are
    compared as written: a 3-character category versus a 4-character subcategory is a disagreement."""
    return sorted((u, c) for u in a.keys() & b.keys() for c in a[u].codes ^ b[u].codes)


def merge(
    a: Mapping[str, Annotation],
    b: Mapping[str, Annotation],
    decisions: Mapping[tuple[str, str], bool],
) -> dict[str, AdjudicatedUnit]:
    """Inputs are not mutated. Decisions for items that are not disagreements raise ValueError."""
    pending = pending_items(a, b)
    unknown = sorted(set(decisions) - set(pending))
    if unknown:
        raise ValueError(f"decisions for items that are not disagreements: {unknown[:10]}")
    missing = [p for p in pending if p not in decisions]
    if missing:
        raise PendingAdjudication(missing)
    out: dict[str, AdjudicatedUnit] = {}
    for u in sorted(a.keys() | b.keys()):
        if u in a and u in b:
            sources = {c: "agreed" for c in a[u].codes & b[u].codes}
            for c in a[u].codes ^ b[u].codes:
                if decisions[u, c]:
                    sources[c] = "adjudicated"
            annotators = (a[u].annotator, b[u].annotator)
        else:
            ann = a[u] if u in a else b[u]
            sources = {c: "single" for c in ann.codes}
            annotators = (ann.annotator,)
        out[u] = AdjudicatedUnit(u, frozenset(sources), sources, annotators)
    return out


def write_adjudicated_csv(units: Iterable[AdjudicatedUnit], path: str | Path) -> None:
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(("unit_id", "codes", "sources", "annotators"))
        for u in units:
            w.writerow(
                [
                    u.unit_id,
                    ";".join(sorted(u.codes)),
                    ";".join(f"{c}:{s}" for c, s in sorted(u.sources.items())),
                    ";".join(u.annotators),
                ]
            )


def read_adjudicated_csv(path: str | Path) -> dict[str, AdjudicatedUnit]:
    out: dict[str, AdjudicatedUnit] = {}
    with open(path, encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            sources = dict(p.split(":", 1) for p in r["sources"].split(";") if p)
            out[r["unit_id"]] = AdjudicatedUnit(
                r["unit_id"], frozenset(sources), sources, tuple(r["annotators"].split(";"))
            )
    return out
