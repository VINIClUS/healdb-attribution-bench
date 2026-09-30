"""Inter-annotator agreement for two coders on the same units (computed before adjudication)."""

from __future__ import annotations

from collections import Counter
from collections.abc import Hashable, Mapping, Sequence
from fractions import Fraction

from habench.annotation.sheets import category

Codes = Mapping[str, frozenset[str]]


def _project(codes: frozenset[str], level: str) -> frozenset[str]:
    if level == "category":
        return frozenset(category(c) for c in codes)
    if level == "subcategory":
        return codes
    raise ValueError(f"unknown level: {level!r}")


def _paired(a: Codes, b: Codes, level: str) -> tuple[list[str], dict[str, frozenset[str]], dict[str, frozenset[str]]]:
    if set(a) != set(b):
        raise ValueError("annotators must cover the same units")
    units = sorted(a)
    return units, {u: _project(a[u], level) for u in units}, {u: _project(b[u], level) for u in units}


def _items(units: list[str], pa: dict[str, frozenset[str]], pb: dict[str, frozenset[str]]):
    """Binary (present_a, present_b) per (unit, category) over the union of annotated categories."""
    cats = sorted(set().union(*pa.values(), *pb.values()))
    return cats, [(c in pa[u], c in pb[u]) for u in units for c in cats]


def percent_agreement(a: Codes, b: Codes, level: str = "category") -> float:
    """Share of (unit, category) items with the same present/absent value; 1.0 if no item exists."""
    _, items = _items(*_paired(a, b, level))
    return sum(x == y for x, y in items) / len(items) if items else 1.0


def cohen_kappa(x: Sequence[Hashable], y: Sequence[Hashable]) -> float | None:
    """Cohen's kappa; None when expected agreement is 1 (degenerate)."""
    if len(x) != len(y) or not x:
        raise ValueError("sequences must be non-empty and of equal length")
    n = len(x)
    cx, cy = Counter(x), Counter(y)
    p_o = Fraction(sum(i == j for i, j in zip(x, y)), n)
    p_e = Fraction(sum(cx[k] * cy[k] for k in cx), n * n)
    if p_e == 1:
        return None
    return float((p_o - p_e) / (1 - p_e))


def cohen_kappa_per_category(a: Codes, b: Codes, level: str = "category") -> dict[str, float | None]:
    units, pa, pb = _paired(a, b, level)
    cats, _ = _items(units, pa, pb)
    return {c: cohen_kappa([c in pa[u] for u in units], [c in pb[u] for u in units]) for c in cats}


def krippendorff_alpha_nominal(data: Sequence[Sequence[Hashable | None]]) -> float | None:
    """Nominal Krippendorff alpha from units x coders (None = missing), coincidence-matrix form.
    Units with fewer than 2 values are ignored; None when D_e == 0."""
    o: Counter[tuple[Hashable, Hashable]] = Counter()
    for unit in data:
        vals = [v for v in unit if v is not None]
        m = len(vals)
        if m < 2:
            continue
        for i, c in enumerate(vals):
            for j, k in enumerate(vals):
                if i != j:
                    o[c, k] += Fraction(1, m - 1)
    n_c: Counter[Hashable] = Counter()
    for (c, _), v in o.items():
        n_c[c] += v
    n = sum(n_c.values())
    d_o = sum(v for (c, k), v in o.items() if c != k)
    d_e = sum(n_c[c] * n_c[k] for c in n_c for k in n_c if c != k)
    if d_e == 0:
        return None
    return float(1 - (n - 1) * d_o / d_e)


def agreement_report(a: Codes, b: Codes) -> dict:
    units, pa, pb = _paired(a, b, "category")
    _, items = _items(units, pa, pb)
    return {
        "n_units": len(units),
        "n_items": len(items),
        "percent_agreement": percent_agreement(a, b),
        "kappa_per_category": cohen_kappa_per_category(a, b),
        "alpha": krippendorff_alpha_nominal([list(t) for t in items]),
    }
