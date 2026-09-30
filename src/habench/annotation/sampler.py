"""Pilot and evaluation sampling with recorded inclusion probabilities (protocol section 12)."""

from __future__ import annotations

import csv
import random
from collections import defaultdict
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Unit:
    """One distinct text; `stratum` encodes change x therapeutic coverage (sampling use only)."""

    unit_id: str
    group_id: str
    stratum: str


@dataclass(frozen=True)
class SampledUnit:
    unit_id: str
    group_id: str
    stratum: str
    phase: str  # "pilot" | "evaluation"
    pi1: float
    weight: float  # 1 / pi1
    double: bool
    pi2: float | None  # conditional probability of double annotation given phase 1
    pi_double: float | None  # pi1 * pi2


def _check_frame(frame: Sequence[Unit]) -> list[Unit]:
    ids = [u.unit_id for u in frame]
    if len(set(ids)) != len(ids):
        raise ValueError("unit_ids are not unique")
    return sorted(frame, key=lambda u: u.unit_id)


def check_disjoint(pilot: Iterable[Unit | SampledUnit], evaluation_frame: Iterable[Unit | SampledUnit]) -> None:
    """Raise ValueError if the pilot and the evaluation frame share any group_id."""
    shared = {u.group_id for u in pilot} & {u.group_id for u in evaluation_frame}
    if shared:
        raise ValueError(f"pilot and evaluation frame share groups: {sorted(shared)}")


def draw_pilot(frame: Sequence[Unit], n: int = 20, *, seed: int) -> tuple[SampledUnit, ...]:
    """Simple random sample without replacement; pilot units train annotators and are not evaluated."""
    units = _check_frame(frame)
    if n > len(units):
        raise ValueError(f"n={n} exceeds frame size {len(units)}")
    pi1 = n / len(units) if units else 1.0
    chosen = random.Random(seed).sample(units, n)
    chosen.sort(key=lambda u: u.unit_id)
    return tuple(
        SampledUnit(u.unit_id, u.group_id, u.stratum, "pilot", pi1, 1 / pi1, False, None, None) for u in chosen
    )


def allocate(sizes: Mapping[str, int], n: int) -> dict[str, int]:
    """Proportional allocation with largest-remainder rounding, capped at stratum size.

    n_h = floor(n * N_h / N) plus one extra unit for the strata with the largest fractional
    parts (ties broken by stratum name). A stratum whose allocation exceeds N_h is fixed at N_h
    and the remaining n is reallocated the same way among the other strata, until none exceeds.
    """
    if n > sum(sizes.values()):
        raise ValueError(f"n={n} exceeds frame size {sum(sizes.values())}")
    fixed: dict[str, int] = {}
    active = {s: size for s, size in sizes.items() if size > 0}
    remaining = n
    while active:
        total = sum(active.values())
        base: dict[str, int] = {}
        rem: dict[str, int] = {}
        for s, size in active.items():
            base[s], rem[s] = divmod(remaining * size, total)  # remainder scaled by total
        extra = remaining - sum(base.values())
        for s in sorted(active, key=lambda s: (-rem[s], s))[:extra]:
            base[s] += 1
        over = [s for s in active if base[s] > active[s]]
        if not over:
            return {**fixed, **base}
        for s in over:
            fixed[s] = active.pop(s)
            remaining -= fixed[s]
    return fixed


def draw_evaluation(
    frame: Sequence[Unit],
    n: int = 130,
    n_double: int = 50,
    *,
    seed: int,
    exclude_groups: Collection[str] = (),
) -> tuple[SampledUnit, ...]:
    """Two-phase sample. Phase 1: stratified SRS without replacement, proportional allocation
    (see `allocate`), pi1 = n_h / N_h. Phase 2: n_double units by SRS from the phase-1 sample get
    double annotation, pi2 = n_double / n, pi_double = pi1 * pi2. Units in `exclude_groups` are
    removed from the frame before allocation. A stratum allocated zero units is not sampled."""
    excluded = set(exclude_groups)
    units = [u for u in _check_frame(frame) if u.group_id not in excluded]
    if n > len(units):
        raise ValueError(f"n={n} exceeds frame size {len(units)} after exclusions")
    if n_double > n:
        raise ValueError(f"n_double={n_double} exceeds n={n}")
    by_stratum: dict[str, list[Unit]] = defaultdict(list)
    for u in units:
        by_stratum[u.stratum].append(u)
    alloc = allocate({s: len(v) for s, v in by_stratum.items()}, n)
    rng = random.Random(seed)
    phase1: list[tuple[Unit, float]] = []
    for s in sorted(by_stratum):
        pi1 = alloc[s] / len(by_stratum[s])
        phase1.extend((u, pi1) for u in rng.sample(by_stratum[s], alloc[s]))
    phase1.sort(key=lambda t: t[0].unit_id)
    double_ids = {u.unit_id for u, _ in rng.sample(phase1, n_double)}
    pi2 = n_double / n if n else 0.0
    return tuple(
        SampledUnit(u.unit_id, u.group_id, u.stratum, "evaluation", p, 1 / p, u.unit_id in double_ids, pi2, p * pi2)
        for u, p in phase1
    )


_FIELDS = ("unit_id", "group_id", "stratum", "phase", "pi1", "weight", "double", "pi2", "pi_double")


def write_sample_csv(units: Iterable[SampledUnit], path: str | Path) -> None:
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(_FIELDS)
        for u in units:
            w.writerow(
                [
                    u.unit_id,
                    u.group_id,
                    u.stratum,
                    u.phase,
                    repr(u.pi1),
                    repr(u.weight),
                    "true" if u.double else "false",
                    "" if u.pi2 is None else repr(u.pi2),
                    "" if u.pi_double is None else repr(u.pi_double),
                ]
            )


def read_sample_csv(path: str | Path) -> tuple[SampledUnit, ...]:
    with open(path, encoding="utf-8", newline="") as fh:
        return tuple(
            SampledUnit(
                r["unit_id"],
                r["group_id"],
                r["stratum"],
                r["phase"],
                float(r["pi1"]),
                float(r["weight"]),
                r["double"] == "true",
                float(r["pi2"]) if r["pi2"] else None,
                float(r["pi_double"]) if r["pi_double"] else None,
            )
            for r in csv.DictReader(fh)
        )


def horvitz_thompson_mean(values: Mapping[str, float], sample: Iterable[SampledUnit]) -> float:
    """Weighted mean sum(w_i y_i) / sum(w_i) with w_i = 1/pi1_i (the Hajek ratio form of the
    Horvitz-Thompson estimator). Every sampled unit must have a value."""
    units = list(sample)
    missing = [u.unit_id for u in units if u.unit_id not in values]
    if missing:
        raise ValueError(f"no value for sampled units: {missing[:5]}")
    if not units:
        raise ValueError("empty sample")
    total = sum(u.weight for u in units)
    return sum(u.weight * values[u.unit_id] for u in units) / total
