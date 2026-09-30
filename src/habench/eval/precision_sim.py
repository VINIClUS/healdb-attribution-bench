"""Precision simulation for sizing H1a (SPEC 13.6). Takes dev/cal-derived arrays; never loads data."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

import numpy as np

DEFAULT_SEED = 20260930


@dataclass(frozen=True)
class PowerResult:
    """P(lower bound > margin) per n and the smallest n reaching the target."""

    n_grid: tuple[int, ...]
    power: tuple[float, ...]
    smallest_n: int | None  # None: the caller declares H1a an estimate (SPEC 13.6, 4.4)


def simulate_power(
    group_sizes: Sequence[int],
    queries_per_group: Sequence[int],
    icc: float,
    *,
    n_grid: Iterable[int] = range(100, 601, 50),
    replicas: int = 1000,
    margin: float = -0.02,
    alpha_level: float = 1 - 0.025 / 3,
    base_coverage: float = 0.6,
    seed: int = DEFAULT_SEED,
    B: int = 500,
    target: float = 0.80,
) -> PowerResult:
    """Power of the H1a non-inferiority test under a true difference of 0.

    Model. Each simulated group draws ``s`` from ``group_sizes`` (empirical contrasts per group) and ``q``
    from ``queries_per_group`` (empirical queries per contrast), so it has ``m = s*q`` queries. A group
    effect ``z ~ N(0, 1)`` shifts the two arms in opposite directions, ``p_A = mu + tau z / 2`` and
    ``p_B = mu - tau z / 2`` (clipped to [0, 1]), with ``mu = base_coverage`` and
    ``tau = sqrt(icc / (1 - icc) * 2 mu (1 - mu))`` so that the intra-group correlation of the paired
    per-query differences is about ``icc``. The true difference is 0 (``E[z] = 0``). The per-group
    coverage counts are ``Binomial(m, p_A)`` and ``Binomial(m, p_B)``; the statistic is the pooled ratio
    difference ``sum(A - B) / sum(m)``.

    Bootstrap. Groups are resampled with replacement (B replicates, vectorized index resampling); the
    lower bound is the ``(1 - alpha_level)`` quantile (one-sided 0.025/3 by default, the worst Holm
    level). Power is the fraction of replicas with lower bound > ``margin``. Each n uses its own
    generator seeded by (seed, n), so results do not depend on the rest of the grid.
    """
    sizes = np.asarray(group_sizes, dtype=int)
    qs = np.asarray(queries_per_group, dtype=int)
    if sizes.size == 0 or qs.size == 0 or sizes.min() < 1 or qs.min() < 1:
        raise ValueError("group_sizes and queries_per_group must be non-empty and positive")
    if not 0.0 <= icc < 1.0:
        raise ValueError("icc must be in [0, 1)")
    mu = base_coverage
    tau = float(np.sqrt(icc / (1.0 - icc) * 2.0 * mu * (1.0 - mu)))
    tail = 1.0 - alpha_level

    grid = tuple(int(n) for n in n_grid)
    power: list[float] = []
    for n in grid:
        rng = np.random.Generator(np.random.PCG64([seed, n]))
        passed = 0
        for _ in range(replicas):
            m = rng.choice(sizes, n) * rng.choice(qs, n)
            z = rng.standard_normal(n)
            p_a = np.clip(mu + tau * z / 2.0, 0.0, 1.0)
            p_b = np.clip(mu - tau * z / 2.0, 0.0, 1.0)
            diff = (rng.binomial(m, p_a) - rng.binomial(m, p_b)).astype(float)
            idx = rng.integers(0, n, size=(B, n))
            ratios = diff[idx].sum(axis=1) / m[idx].sum(axis=1)
            if np.quantile(ratios, tail) > margin:
                passed += 1
        power.append(passed / replicas)
    smallest = next((n for n, p in zip(grid, power) if p >= target), None)
    return PowerResult(grid, tuple(power), smallest)
