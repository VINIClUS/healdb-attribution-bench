"""Statistical analysis primitives (SPEC 13): cluster bootstrap, p-values, Holm, exact bounds, risks."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

import numpy as np
from scipy.stats import beta

from habench.types import CATEGORICAL

DEFAULT_SEED = 20260930
STABILITY_SEEDS = (20260930, 20260931, 20260932)
IDENTITY_NOTE = "identidade por construção"

_CORRECT = "correto_sustentado"
_WRONG = frozenset({"errado", "indevidamente_exclusivo"})
_UNCOMMITTED = "nao_comprometido"
_CATEGORICAL_STATES = frozenset(str(s) for s in CATEGORICAL)


@dataclass(frozen=True)
class BootstrapResult:
    """Point estimate and B replicate values of a paired cluster bootstrap."""

    estimate: float
    replicates: np.ndarray

    @property
    def B(self) -> int:
        return int(self.replicates.size)

    def upper(self, q: float) -> float:
        """Percentile ``q`` (in [0, 100]) of the replicates."""
        return float(np.percentile(self.replicates, q))

    def lower(self, q: float) -> float:
        """Percentile ``q`` (in [0, 100]) of the replicates; same as ``upper``, named for intent."""
        return float(np.percentile(self.replicates, q))

    def ci(self, level: float = 0.95) -> tuple[float, float]:
        tail = (1.0 - level) / 2.0 * 100.0
        return self.lower(tail), self.upper(100.0 - tail)

    @property
    def identity_by_construction(self) -> bool:
        """True when the estimate and every replicate are exactly 0 (SPEC 13.1, A05)."""
        return self.estimate == 0.0 and bool(np.all(self.replicates == 0.0))


def paired_cluster_bootstrap(
    groups: Sequence[object],
    stat: Callable[[list], float],
    *,
    B: int = 2000,
    seed: int = DEFAULT_SEED,
) -> BootstrapResult:
    """Resample groups with replacement; ``stat`` recomputes both arms on the resampled groups."""
    n = len(groups)
    if n == 0:
        raise ValueError("no groups to resample")
    rng = np.random.Generator(np.random.PCG64(seed))
    idx = rng.integers(0, n, size=(B, n))
    reps = np.fromiter((stat([groups[i] for i in row]) for row in idx), dtype=float, count=B)
    return BootstrapResult(estimate=float(stat(list(groups))), replicates=reps)


@dataclass(frozen=True)
class StabilityResult:
    """Outcome of the seed-stability check (SPEC 13.2)."""

    seeds: tuple[int, ...]
    intervals: tuple[tuple[float, float], ...]
    max_shift: float
    stable: bool
    recommended_B: int


def stability_check(
    groups: Sequence[object],
    stat: Callable[[list], float],
    *,
    B: int = 2000,
    seeds: Sequence[int] = STABILITY_SEEDS,
    tol: float = 0.005,
) -> StabilityResult:
    """Repeat the 95% CI over seeds; unstable when any limit moves more than ``tol`` (then B = 10000)."""
    cis = tuple(paired_cluster_bootstrap(groups, stat, B=B, seed=s).ci() for s in seeds)
    lows = [c[0] for c in cis]
    highs = [c[1] for c in cis]
    shift = max(max(lows) - min(lows), max(highs) - min(highs))
    stable = shift <= tol
    return StabilityResult(tuple(seeds), cis, float(shift), stable, B if stable else 10000)


def ni_pvalue(deltas: Iterable[float], margin: float = -0.02) -> float:
    """Non-inferiority p = (1 + #{d <= margin}) / (B + 1) (SPEC 13.2, R16)."""
    d = np.asarray(list(deltas), dtype=float)
    return float((1 + np.count_nonzero(d <= margin)) / (d.size + 1))


def sup_pvalue(deltas: Iterable[float]) -> float:
    """Superiority p = (1 + #{d <= 0}) / (B + 1) (SPEC 13.2, R16)."""
    return ni_pvalue(deltas, 0.0)


def holm(pvalues: Sequence[float], alpha: float = 0.025) -> list[bool]:
    """Holm step-down; rejections in input order. Unexecuted contrasts must enter as p = 1."""
    m = len(pvalues)
    order = sorted(range(m), key=lambda i: pvalues[i])
    reject = [False] * m
    for rank, i in enumerate(order):
        if pvalues[i] <= alpha / (m - rank):
            reject[i] = True
        else:
            break
    return reject


def p_h2(p_i: float, p_ii: float) -> float:
    """Intersection-union p-value of the composite H2 (SPEC 13.1, A08)."""
    return max(p_i, p_ii)


def _check_counts(k: int, n: int) -> None:
    if n <= 0 or not 0 <= k <= n:
        raise ValueError(f"invalid counts k={k}, n={n}")


def clopper_pearson_upper(k: int, n: int, alpha: float = 0.025) -> float:
    """One-sided exact upper limit at level 1 - alpha (SPEC 13.4); k = 0 gives 1 - alpha**(1/n)."""
    _check_counts(k, n)
    if k == n:
        return 1.0
    return float(beta.ppf(1.0 - alpha, k + 1, n - k))


def clopper_pearson_lower(k: int, n: int, alpha: float = 0.025) -> float:
    """One-sided exact lower limit at level 1 - alpha."""
    _check_counts(k, n)
    if k == 0:
        return 0.0
    return float(beta.ppf(alpha, k, n - k + 1))


def coverage(outcomes: Sequence[str]) -> float:
    """#correto_sustentado / n; ``falha`` and everything else stay in the denominator (SPEC 10.2)."""
    if not outcomes:
        return 0.0
    return sum(1 for o in outcomes if str(o) == _CORRECT) / len(outcomes)


def _risk(pairs: Sequence[tuple[str, str]]) -> float:
    if not pairs:
        return 0.0
    return sum(1 for _, o in pairs if str(o) in _WRONG) / len(pairs)


def selective_risk(pairs: Iterable[tuple[str, str]]) -> float:
    """(#errado + #indevidamente_exclusivo) / #categorical over (state, outcome) pairs; 0.0 if empty."""
    return _risk([(s, o) for s, o in pairs if str(s) in _CATEGORICAL_STATES])


def committed_risk(pairs: Iterable[tuple[str, str]]) -> float:
    """Same numerator over categorical outputs minus ``nao_comprometido``; 0.0 if empty."""
    return _risk(
        [(s, o) for s, o in pairs if str(s) in _CATEGORICAL_STATES and str(o) != _UNCOMMITTED]
    )


def h1b_guard(risk_deltas_bootstrap: Iterable[float], margin: float = 0.02) -> bool:
    """True when the 97.5th percentile of the risk differences (with - without) is <= margin (SPEC 13.1, A06)."""
    d = np.asarray(list(risk_deltas_bootstrap), dtype=float)
    return bool(np.percentile(d, 97.5) <= margin)


@dataclass(frozen=True)
class NonInferiority:
    """Non-inferiority verdict for one contrast."""

    estimate: float
    ci: tuple[float, float]
    pvalue: float
    reject: bool
    identity_by_construction: bool
    note: str = ""


def noninferiority(
    result: BootstrapResult, margin: float = -0.02, alpha: float = 0.025
) -> NonInferiority:
    """NI test from a bootstrap result; identity by construction is never reported as rejection (SPEC 13.1)."""
    p = ni_pvalue(result.replicates, margin)
    identity = result.identity_by_construction
    return NonInferiority(
        estimate=result.estimate,
        ci=result.ci(),
        pvalue=p,
        reject=(p <= alpha) and not identity,
        identity_by_construction=identity,
        note=IDENTITY_NOTE if identity else "",
    )
