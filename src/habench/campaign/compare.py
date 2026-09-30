"""Level-1/level-2 equality of repeated ACM responses and comparison of repeated translations (§5.2, §9)."""

import hashlib
import json
import re
import statistics
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from itertools import combinations
from typing import Any


def level1_sha256(raw_body: bytes) -> str:
    """Level 1: exact bytes of the raw HTTP body."""
    return hashlib.sha256(raw_body).hexdigest()


def level2_canonical(response: Mapping[str, Any]) -> str:
    """Drop only the top-level ResponseMetadata, then canonical JSON. Arrays keep their order (§5.2)."""
    body = {k: v for k, v in response.items() if k != "ResponseMetadata"}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def level2_sha256(response: Mapping[str, Any]) -> str:
    return hashlib.sha256(level2_canonical(response).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class AcmObservation:
    """key identifies the repeated condition, e.g. "acm_isolated|<medication>"."""

    call_id: str
    key: str
    model_version: str | None
    raw_sha256: str | None
    level2_sha256: str | None
    ok: bool


@dataclass(frozen=True, slots=True)
class AcmComparison:
    key: str
    model_version: str | None
    n_ok: int
    n_failed: int
    n_distinct_level1: int
    n_distinct_level2: int
    n_pairs: int
    n_pairs_differing_level2: int


def _pairs(n: int) -> int:
    return n * (n - 1) // 2


def compare_acm(observations: Iterable[AcmObservation]) -> list[AcmComparison]:
    """One row per (key, model_version) stratum; failed calls are counted apart, never as content."""
    strata: dict[tuple[str, str | None], list[AcmObservation]] = defaultdict(list)
    for o in observations:
        strata[(o.key, o.model_version)].append(o)
    rows = []
    for (key, version), obs in sorted(strata.items(), key=lambda kv: (kv[0][0], kv[0][1] or "")):
        ok = [o for o in obs if o.ok]
        if any(o.raw_sha256 is None or o.level2_sha256 is None for o in ok):
            raise ValueError(f"ok observation without hashes in stratum {key!r}")
        counts: dict[str | None, int] = defaultdict(int)
        for o in ok:
            counts[o.level2_sha256] += 1
        same = sum(_pairs(c) for c in counts.values())
        rows.append(AcmComparison(
            key=key, model_version=version, n_ok=len(ok), n_failed=len(obs) - len(ok),
            n_distinct_level1=len({o.raw_sha256 for o in ok}), n_distinct_level2=len(counts),
            n_pairs=_pairs(len(ok)), n_pairs_differing_level2=_pairs(len(ok)) - same))
    return rows


def model_versions_by_key(observations: Iterable[AcmObservation]) -> dict[str, frozenset[str]]:
    """Model versions seen per key among ok calls."""
    seen: dict[str, set[str]] = defaultdict(set)
    for o in observations:
        seen[o.key]  # keep keys that only have failed calls
        if o.ok and o.model_version is not None:
            seen[o.key].add(o.model_version)
    return {k: frozenset(v) for k, v in seen.items()}


_WS = re.compile(r"\s+")


def normalize_ws(s: str) -> str:
    """Collapse any run of Unicode whitespace to one space and strip."""
    return _WS.sub(" ", s).strip()


def levenshtein(a: str, b: str) -> int:
    """Character edit distance; O(len(a)·len(b)) time, O(min(len)) memory."""
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


@dataclass(frozen=True, slots=True)
class TranslationObservation:
    """key like "<medication>|<profile>"."""

    call_id: str
    key: str
    text: str | None
    ok: bool


@dataclass(frozen=True, slots=True)
class TranslationComparison:
    key: str
    n_ok: int
    n_failed: int
    n_distinct_exact: int
    n_distinct_normalized: int
    n_pairs: int
    n_pairs_differing_exact: int
    n_pairs_differing_normalized: int
    edit_min: int | None  # over unordered pairs of ok texts; None when fewer than 2 ok texts
    edit_median: float | None
    edit_max: int | None
    edit_mean: float | None
    norm_edit_mean: float | None  # distance / max(len a, len b), 0 when both empty


def compare_translations(observations: Iterable[TranslationObservation]) -> list[TranslationComparison]:
    by_key: dict[str, list[TranslationObservation]] = defaultdict(list)
    for o in observations:
        by_key[o.key].append(o)
    rows = []
    for key in sorted(by_key):
        obs = by_key[key]
        texts: list[str] = []
        for o in obs:
            if o.ok:
                if o.text is None:
                    raise ValueError(f"ok observation without text: {o.call_id!r}")
                texts.append(o.text)
        norm = [normalize_ws(t) for t in texts]
        dists: list[int] = []
        norm_dists: list[float] = []
        differing_exact = differing_norm = 0
        for i, j in combinations(range(len(texts)), 2):
            d = levenshtein(texts[i], texts[j])
            dists.append(d)
            longest = max(len(texts[i]), len(texts[j]))
            norm_dists.append(d / longest if longest else 0.0)
            differing_exact += texts[i] != texts[j]
            differing_norm += norm[i] != norm[j]
        rows.append(TranslationComparison(
            key=key, n_ok=len(texts), n_failed=len(obs) - len(texts),
            n_distinct_exact=len(set(texts)), n_distinct_normalized=len(set(norm)),
            n_pairs=len(dists), n_pairs_differing_exact=differing_exact,
            n_pairs_differing_normalized=differing_norm,
            edit_min=min(dists) if dists else None,
            edit_median=statistics.median(dists) if dists else None,
            edit_max=max(dists) if dists else None,
            edit_mean=statistics.fmean(dists) if dists else None,
            norm_edit_mean=statistics.fmean(norm_dists) if norm_dists else None))
    return rows


def summary_rows(acm: Iterable[AcmComparison] = (),
                 translations: Iterable[TranslationComparison] = ()) -> list[dict[str, Any]]:
    """Flatten comparisons for CSV/JSON output; ``kind`` tells the row types apart."""
    return ([{"kind": "acm", **asdict(r)} for r in acm]
            + [{"kind": "translation", **asdict(r)} for r in translations])
