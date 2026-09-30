"""Study A (b): translation variability. Identical Portuguese indication texts, distinct English translations.

Groups of >= 2 medications of the universe (medications with a V1 response) sharing the same normalized
Portuguese text (`habench.data.groups.normalize_pt`) or the same raw `ds_indication.strip()`. English
variants are compared on `ds_indication_eng.strip()` by character Levenshtein distance. Only aggregates
are produced; the partition label of a group is read from the split manifest, never the test truth.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Mapping
from itertools import combinations

import numpy as np

from habench.data.groups import normalize_pt

COMPARED = (
    "medications with a V1 response, grouped by identical Portuguese text (key: normalize_pt, or raw "
    "ds_indication.strip()); English variants are the distinct ds_indication_eng.strip() values of a group; "
    "distance is the character (code point) Levenshtein distance over all pairs of distinct variants; "
    "normalized distance = distance / max(length); percentiles by linear interpolation (numpy default)."
)


def levenshtein_dp(a: str, b: str) -> int:
    """Reference O(len(a) * len(b)) dynamic program with a single row buffer."""
    if len(a) < len(b):
        a, b = b, a
    row = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        prev, row[0] = row[0], i
        for j, cb in enumerate(b, 1):
            cur = min(row[j] + 1, row[j - 1] + 1, prev + (ca != cb))
            prev, row[j] = row[j], cur
    return row[len(b)]


def levenshtein(a: str, b: str) -> int:
    """Exact Levenshtein distance by the bit-parallel algorithm (Myers 1999, Hyyro 2003) on Python integers.

    Same result as `levenshtein_dp` in O(len(a) * ceil(len(b) / word)) big-integer steps; used because
    all pairs of long texts are compared.
    """
    if len(a) < len(b):
        a, b = b, a
    m = len(b)
    if m == 0:
        return len(a)
    peq: dict[str, int] = {}
    for i, c in enumerate(b):
        peq[c] = peq.get(c, 0) | (1 << i)
    mask = (1 << m) - 1
    top = 1 << (m - 1)
    pv, mv, score = mask, 0, m
    for c in a:
        eq = peq.get(c, 0)
        xv = eq | mv
        xh = (((eq & pv) + pv) ^ pv) | eq
        ph = mv | ~(xh | pv)
        mh = pv & xh
        if ph & top:
            score += 1
        elif mh & top:
            score -= 1
        ph = ((ph << 1) | 1) & mask
        mh = (mh << 1) & mask
        pv = (mh | ~(xv | ph)) & mask
        mv = ph & xv
    return score


def summarize(values: list[float] | list[int]) -> dict:
    if not values:
        return {"n": 0, "min": None, "median": None, "p90": None, "max": None}
    arr = np.asarray(values, dtype=np.float64)
    return {
        "n": len(values),
        "min": float(arr.min()),
        "median": float(np.percentile(arr, 50)),
        "p90": float(np.percentile(arr, 90)),
        "max": float(arr.max()),
    }


def analyze(
    key_of: Callable[[str], str],
    texts: Mapping[int, tuple[str, str]],
    partition_of: Callable[[int], str],
) -> dict:
    """Aggregates for the full corpus and for dev+cal versus other partitions (reserve and test together)."""
    by_key: dict[str, list[int]] = defaultdict(list)
    for m in sorted(texts):
        by_key[key_of(texts[m][0])].append(m)
    scopes = {"full_corpus": lambda p: True, "dev_cal": lambda p: p in ("dev", "cal"),
              "other_partitions": lambda p: p not in ("dev", "cal")}
    acc = {s: {"groups": 0, "meds": 0, "n_multi": 0, "n_distinct": [], "abs": [], "norm": []} for s in scopes}
    cache: dict[tuple[str, str], int] = {}
    for meds in by_key.values():
        if len(meds) < 2:
            continue
        variants = sorted({texts[m][1].strip() for m in meds})
        part = partition_of(meds[0])
        dists = []
        for a, b in combinations(variants, 2):
            d = cache.get((a, b))
            if d is None:
                d = cache[(a, b)] = levenshtein(a, b)
            dists.append((d, d / max(len(a), len(b), 1)))
        for s, pred in scopes.items():
            if not pred(part):
                continue
            r = acc[s]
            r["groups"] += 1
            r["meds"] += len(meds)
            r["n_distinct"].append(len(variants))
            if len(variants) > 1:
                r["n_multi"] += 1
            r["abs"].extend(d for d, _ in dists)
            r["norm"].extend(n for _, n in dists)
    return {
        s: {
            "n_groups_with_repeats": r["groups"],
            "n_meds_in_groups": r["meds"],
            "n_groups_with_distinct_english": r["n_multi"],
            "distinct_english_per_group": summarize(r["n_distinct"]),
            "n_english_variant_pairs": len(r["abs"]),
            "distance_absolute": summarize(r["abs"]),
            "distance_normalized": summarize(r["norm"]),
        }
        for s, r in acc.items()
    }


def compute() -> dict:
    from habench.data.groups import load_texts
    from habench.data.splits import partition_of_med

    texts = load_texts("v1")
    part = partition_of_med
    return {
        "compared": COMPARED,
        "n_medications": len(texts),
        "by_normalized_pt": analyze(normalize_pt, texts, part),
        "by_raw_pt_strip": analyze(str.strip, texts, part),
    }
