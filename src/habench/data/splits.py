"""Dev/cal/test/reserve partitions of whole document groups, and the test-partition sealing API."""

from __future__ import annotations

import csv
import functools
import math
import sys
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from habench.types import SealedError

SEED = 20260930
N_SAMPLE = 1000
N_DEV, N_CAL, N_TEST = 200, 200, 600
EXTEND_SAMPLE = Path("/home/vinicius/healdb-reconstrucao/out/extend_amostra.csv")
F1_LIST = frozenset({
    4, 7, 560, 3205, 4139, 298, 1093, 2188, 2201, 3297, 3298, 3300, 3302, 3819, 3866, 4098, 4825, 7294,
    7683, 8763, 8764, 10036, 10331,
})
REPRO_DIR = Path(__file__).parents[3] / "repro"
MANIFEST_PATH = REPRO_DIR / "split_manifest.csv"
CORPUS_PATH = REPRO_DIR / "corpus_groups.csv"
STRATA_PATH = Path("/home/vinicius/hab-data/corpus/strata.csv")
PARTITIONS = ("dev", "cal", "test", "reserve")


def allocate(total: int, weights: Mapping[str, int], caps: Mapping[str, int] | None = None) -> dict[str, int]:
    """Proportional allocation of `total` by largest remainder (ties by key), each share capped."""
    caps = caps if caps is not None else dict(weights)
    keys = sorted(weights)
    w = sum(weights.values())
    if total > sum(caps[k] for k in keys):
        raise ValueError("allocation exceeds capacity")
    exact = {k: total * weights[k] / w for k in keys}
    out = {k: min(math.floor(exact[k]), caps[k]) for k in keys}
    left = total - sum(out.values())
    while left > 0:
        open_ = [k for k in keys if out[k] < caps[k]]
        for k in sorted(open_, key=lambda k: (-(exact[k] - out[k]), k))[:left]:
            out[k] += 1
            left -= 1
    return out


@dataclass(frozen=True, slots=True)
class SplitRow:
    group_id: str
    partition: str
    medications: tuple[int, ...]
    stratum: str
    inclusion_prob: float


def forced_medications() -> set[int]:
    with open(EXTEND_SAMPLE, newline="", encoding="utf-8") as fh:
        extend = {int(r["id_medication"]) for r in csv.DictReader(fh)}
    return extend | F1_LIST


def assign_splits(
    groups: Iterable[tuple[str, tuple[int, ...]]], stratum_of: Mapping[str, str], forced_meds: Iterable[int]
) -> list[SplitRow]:
    groups = sorted(groups)
    forced_set = set(forced_meds)
    forced = [g for g in groups if forced_set & set(g[1])]
    forced_ids = {g[0] for g in forced}
    rows = [SplitRow(gid, "dev", meds, stratum_of[gid], 1.0) for gid, meds in forced]
    pool: dict[str, list[tuple[str, tuple[int, ...]]]] = defaultdict(list)
    for g in groups:
        if g[0] not in forced_ids:
            pool[stratum_of[g[0]]].append(g)
    N = {s: len(v) for s, v in pool.items()}
    n_h = allocate(N_SAMPLE, N)
    dev_h = allocate(N_DEV, n_h)
    cal_h = allocate(N_CAL, n_h, {s: n_h[s] - dev_h[s] for s in n_h})
    rng = np.random.default_rng(SEED)
    for s in sorted(pool):
        order = rng.permutation(len(pool[s]))
        n, d, c = n_h[s], dev_h[s], cal_h[s]
        for rank, ix in enumerate(order):
            gid, meds = pool[s][int(ix)]
            if rank < d:
                part, k = "dev", d
            elif rank < d + c:
                part, k = "cal", c
            elif rank < n:
                part, k = "test", n - d - c
            else:
                part, k = "reserve", N[s] - n
            rows.append(SplitRow(gid, part, meds, s, k / N[s]))
    return sorted(rows, key=lambda r: r.group_id)


def write_manifest(path: Path, rows: Iterable[SplitRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["group_id", "partition", "medications", "n_medications", "stratum", "inclusion_prob"])
        for r in sorted(rows, key=lambda r: r.group_id):
            w.writerow([r.group_id, r.partition, ";".join(map(str, r.medications)), len(r.medications), r.stratum, repr(r.inclusion_prob)])


def write_corpus(path: Path, records) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["group_id", "medication", "pt_sha256", "en_sha256", "link"])
        for r in sorted(records, key=lambda r: r.medication):
            w.writerow([r.group_id, r.medication, r.pt_sha256, r.en_sha256, r.link])


@dataclass(frozen=True)
class Build:
    groups: list
    records: list
    rows: list[SplitRow]
    feats: dict
    stratum_of: dict[str, str]
    missing_forced: list[int]
    missing_translations: list[int]


def build() -> Build:
    """Full deterministic build from the v1 snapshot (no writes)."""
    from habench.data import groups as G
    from habench.data import sampling as S
    from habench.pipeline.mapping import load_hierarchy

    responses = S.load_responses("v1")
    texts = G.load_texts("v1")
    miss_tr = sorted(set(responses) - set(texts))
    groups, records = G.build_groups({m: texts[m] for m in sorted(responses) if m in texts})
    feats = {f.medication: f for f in S.med_features({m: responses[m] for m in texts}, texts, load_hierarchy("v1"))}
    pairs = [(g.group_id, g.meds) for g in groups]
    stratum_of = S.group_strata(pairs, feats)
    forced = forced_medications()
    rows = assign_splits(pairs, stratum_of, forced)
    return Build(groups, records, rows, feats, stratum_of, sorted(forced - set(texts)), miss_tr)


def write_all(b: Build) -> None:
    from habench.data import sampling as S

    write_manifest(MANIFEST_PATH, b.rows)
    write_corpus(CORPUS_PATH, b.records)
    S.write_strata(STRATA_PATH, b.feats, {r.medication: r.group_id for r in b.records}, b.stratum_of)


# ---- sealing API -------------------------------------------------------------------------------------


@functools.lru_cache(maxsize=None)
def _load_manifest(path: Path) -> tuple[dict[str, tuple[int, ...]], dict[int, str]]:
    by_part: dict[str, list[int]] = {p: [] for p in PARTITIONS}
    part_of: dict[int, str] = {}
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            for m in r["medications"].split(";"):
                by_part[r["partition"]].append(int(m))
                part_of[int(m)] = r["partition"]
    return {p: tuple(sorted(v)) for p, v in by_part.items()}, part_of


def _manifest() -> tuple[dict[str, tuple[int, ...]], dict[int, str]]:
    return _load_manifest(MANIFEST_PATH)


def partition_of_med(med: int) -> str:
    return _manifest()[1][med]


def meds_in(partition: str) -> tuple[int, ...]:
    if partition == "test":
        raise SealedError("the test partition is sealed")
    if partition not in PARTITIONS:
        raise ValueError(f"unknown partition {partition!r}")
    return _manifest()[0][partition]


def check_not_sealed(meds: Iterable[int]) -> None:
    part_of = _manifest()[1]
    if any(part_of.get(m) == "test" for m in meds):
        raise SealedError("medications from the sealed test partition")


def evidence_for(partition: str, snap: str = "v1"):
    meds = meds_in(partition)  # raises SealedError for "test" before anything is loaded
    from habench.pipeline.evidence import load_evidence

    return load_evidence(snap, meds)


# ---- CLI ----------------------------------------------------------------------------------------------


def _report(b: Build) -> None:
    from habench.data.groups import summarize

    meds_of = {r.group_id: r.medications for r in b.rows}
    print("groups/medications per partition:")
    for p in PARTITIONS:
        gs = [r for r in b.rows if r.partition == p]
        print(f"  {p}: {len(gs)} groups, {sum(len(r.medications) for r in gs)} medications")
    print("forced dev groups:", sum(1 for r in b.rows if r.partition == "dev" and r.inclusion_prob == 1.0))
    s = summarize(b.groups, len(b.records))
    print("groups:", s["groups"], "size distribution:", s["size_distribution"])
    print("largest group:", s["largest_group"], "size", s["largest_size"], "members", meds_of[s["largest_group"]][:10], "...")
    print("groups over 1% of medications:", s["over_1pct"] or "none")
    print("forced ids not in universe:", b.missing_forced or "none")
    print("universe medications without translate row:", b.missing_translations or "none")
    counts: dict[str, int] = defaultdict(int)
    for r in b.rows:
        counts[r.stratum] += 1
    print("strata (groups):", dict(sorted(counts.items())))


def main(argv: list[str]) -> int:
    if argv != ["build"]:
        print("usage: python -m habench.data.splits build", file=sys.stderr)
        return 2
    b = build()
    write_all(b)
    _report(b)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
