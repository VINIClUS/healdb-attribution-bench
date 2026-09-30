"""Study A (c): the real contrast "V1 post-processing -> V2 post-processing" on the same V1 responses.

For an evidence set, all 2^|D| hybrids of the bundle `V1_TO_V2` are run in the WHO key space. Each
association gets its presence vector over the hybrids (bit `s` = present under the hybrid whose factor
set is the subset encoded by `s`; bit j of `s` is factor j of `factor_order()`). For an association whose
state differs between the empty set and D, the family of inclusion-minimal sufficient sets is derived from
that vector (protocol 7.2). Only aggregates leave this module.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from functools import lru_cache

from habench.pipeline import catalog, core
from habench.pipeline.evidence import Evidence
from habench.pipeline.mapping import Hierarchy
from habench.types import AssocKey


def factor_order() -> tuple[str, ...]:
    """D of the bundle V1_TO_V2, sorted: bit j of a subset code is factor j."""
    return tuple(sorted(catalog.V1.diff(catalog.V2)))


def presence_masks(ev: Evidence, hier: Hierarchy) -> dict[AssocKey, int]:
    """Per association present in at least one hybrid: its presence vector as an integer of 2^|D| bits."""
    names = factor_order()
    masks: dict[AssocKey, int] = {}
    for s in range(1 << len(names)):
        subset = frozenset(n for j, n in enumerate(names) if s >> j & 1)
        cfg = catalog.hybrid(catalog.V1, catalog.V2, subset)
        bit = 1 << s
        for key in core.run(cfg, ev, hier, core.WHO).present:
            masks[key] = masks.get(key, 0) | bit
    return masks


@lru_cache(maxsize=None)
def _submasks(s: int) -> tuple[int, ...]:
    """Proper submasks of s."""
    if s == 0:
        return ()
    out, t = [], (s - 1) & s
    while True:
        out.append(t)
        if t == 0:
            break
        t = (t - 1) & s
    return tuple(out)


def _bit(table: int, s: int) -> int:
    return table >> s & 1


def minimal_family(table: int, n: int) -> tuple[frozenset[int], bool]:
    """(family of inclusion-minimal sufficient subset codes, non-monotone flag) of one presence vector.

    S is sufficient iff the state under S equals the state under D (all factors). The vector must change
    between the empty set and D; otherwise the empty set is sufficient and the family is {0}.
    """
    full = (1 << n) - 1
    target = _bit(table, full)
    sufficient = frozenset(s for s in range(1 << n) if _bit(table, s) == target)
    minimal = frozenset(s for s in sufficient if not any(t in sufficient for t in _submasks(s)))
    non_monotone = any(
        (t & s) == s and t not in sufficient for s in sufficient for t in range(1 << n) if t != s
    )
    return minimal, non_monotone


def summarize_tables(tables: Mapping[int, int], n: int) -> dict:
    """Aggregate of {truth table: number of associations} restricted to associations whose state changes."""
    full = (1 << n) - 1
    shape: Counter[int] = Counter()
    participation = [0] * n
    non_monotone = appear = disappear = changed = 0
    distinct = 0
    for table, count in tables.items():
        if _bit(table, 0) == _bit(table, full):
            continue
        changed += count
        distinct += 1
        if _bit(table, full):
            appear += count
        else:
            disappear += count
        minimal, nm = minimal_family(table, n)
        shape[len(minimal)] += count
        union = 0
        for m in minimal:
            union |= m
        for j in range(n):
            if union >> j & 1:
                participation[j] += count
        if nm:
            non_monotone += count
    return {
        "n_changed": changed,
        "appear": appear,
        "disappear": disappear,
        "shape_histogram": {str(k): v for k, v in sorted(shape.items())},
        "participation": dict(zip(factor_order(), participation)),
        "non_monotone": non_monotone,
        "distinct_truth_tables_changed": distinct,
    }


def contrast_stats(ev: Evidence, hier: Hierarchy) -> dict:
    n = len(factor_order())
    full = (1 << n) - 1
    masks = presence_masks(ev, hier)
    tables = Counter(masks.values())
    stats = summarize_tables(tables, n)
    stats.update(
        n_medications=len(ev.meds),
        n_keys_v1=sum(1 for m in masks.values() if m & 1),
        n_keys_v2=sum(1 for m in masks.values() if m >> full & 1),
        n_keys_union=len(masks),
        distinct_truth_tables_all=len(tables),
        n_hybrids=1 << n,
        factors=list(factor_order()),
    )
    return stats


def load_scopes() -> dict[str, Evidence]:
    """Evidence per reporting scope: dev+cal (allowed) and the full corpus (descriptive only, deviation D2)."""
    from habench.data import splits
    from habench.pipeline.evidence import load_evidence

    meds = sorted(set(splits.meds_in("dev")) | set(splits.meds_in("cal")))
    return {"dev_cal": load_evidence("v1", meds), "full_corpus": load_evidence("v1")}


def compute(scopes: Iterable[str] = ("dev_cal", "full_corpus")) -> dict:
    from habench.pipeline.mapping import load_hierarchy

    hier = load_hierarchy("v1")
    evs = load_scopes()
    out = {}
    for name in scopes:
        stats = contrast_stats(evs[name], hier)
        stats["scope_note"] = (
            "development and calibration partitions" if name == "dev_cal"
            else "full corpus, descriptive only (deviation D2), not confirmatory"
        )
        out[name] = stats
    return out
