from itertools import permutations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from habench.annotation.agreement import (
    agreement_report,
    cohen_kappa,
    cohen_kappa_per_category,
    krippendorff_alpha_nominal,
    percent_agreement,
)


def test_kappa_perfect_and_chance():
    assert cohen_kappa([1, 0, 1, 0], [1, 0, 1, 0]) == pytest.approx(1.0)
    # independent margins, 50/50: p_o = 0.5 = p_e
    assert cohen_kappa([1, 1, 0, 0], [1, 0, 1, 0]) == pytest.approx(0.0)


def test_kappa_2x2_by_formula():
    a, b, c, d = 20, 5, 10, 15  # a: both yes, b: x yes y no, c: x no y yes, d: both no
    x = [1] * (a + b) + [0] * (c + d)
    y = [1] * a + [0] * b + [1] * c + [0] * d
    n = a + b + c + d
    p_o = (a + d) / n
    p_e = ((a + b) * (a + c) + (c + d) * (b + d)) / n**2
    assert cohen_kappa(x, y) == pytest.approx((p_o - p_e) / (1 - p_e))


def test_kappa_degenerate_none():
    assert cohen_kappa([1, 1, 1], [1, 1, 1]) is None
    assert cohen_kappa(["a"], ["a"]) is None


A = {"u1": frozenset({"J45", "E11"}), "u2": frozenset({"E11"}), "u3": frozenset(), "u4": frozenset({"J45"})}
B = {"u1": frozenset({"J45"}), "u2": frozenset({"E11"}), "u3": frozenset(), "u4": frozenset({"J45", "I10"})}


def test_per_category_and_percent():
    kappas = cohen_kappa_per_category(A, B)
    assert set(kappas) == {"E11", "I10", "J45"}
    assert kappas["J45"] == pytest.approx(1.0)
    assert cohen_kappa_per_category({"u": frozenset({"X10"})}, {"u": frozenset({"X10"})}) == {"X10": None}
    # 12 items (3 categories x 4 units), disagreements: (u1,E11), (u4,I10)
    assert percent_agreement(A, B) == pytest.approx(10 / 12)


def test_subcategory_level():
    a = {"u1": frozenset({"J450"}), "u2": frozenset()}
    b = {"u1": frozenset({"J451"}), "u2": frozenset()}
    assert percent_agreement(a, b, "category") == 1.0
    assert percent_agreement(a, b, "subcategory") == 0.5  # 2 codes x 2 units, only u2 agrees
    with pytest.raises(ValueError):
        percent_agreement(a, b, "other")


def test_report_and_unit_mismatch():
    r = agreement_report(A, B)
    assert r["n_units"] == 4 and r["n_items"] == 12
    assert r["percent_agreement"] == pytest.approx(10 / 12)
    assert set(r["kappa_per_category"]) == {"E11", "I10", "J45"}
    assert r["alpha"] is not None
    with pytest.raises(ValueError):
        agreement_report(A, {"u1": frozenset()})


def test_alpha_perfect():
    assert krippendorff_alpha_nominal([[1, 1], [0, 0], [1, 1], [0, 0]]) == pytest.approx(1.0)


def test_alpha_degenerate_and_ignored_units():
    assert krippendorff_alpha_nominal([[1, 1], [1, 1]]) is None
    assert krippendorff_alpha_nominal([[1, None], [None, 0]]) is None
    assert krippendorff_alpha_nominal([[1, None], [1, 0], [0, 0]]) is not None


def brute_alpha(data):
    """D_o and D_e by enumerating ordered pairs of pairable values (no coincidence matrix)."""
    slots = [(u, v) for u, unit in enumerate(data) for v in unit if v is not None]
    pairable = [(u, v) for u, v in slots if sum(w is not None for w in data[u]) >= 2]
    n = len(pairable)
    if n < 2:
        return None
    d_o = 0.0
    for (u1, v1), (u2, v2) in permutations(pairable, 2):
        if u1 == u2 and v1 != v2:
            m = sum(w is not None for w in data[u1])
            d_o += 1 / (m - 1)
    d_o /= n
    d_e = sum(v1 != v2 for (_, v1), (_, v2) in permutations(pairable, 2)) / (n * (n - 1))
    return None if d_e == 0 else 1 - d_o / d_e


@given(
    st.lists(
        st.lists(st.one_of(st.none(), st.integers(0, 3)), min_size=2, max_size=4),
        min_size=1,
        max_size=12,
    )
)
@settings(max_examples=200, deadline=None)
def test_alpha_matches_brute_force(data):
    got, want = krippendorff_alpha_nominal(data), brute_alpha(data)
    if want is None:
        assert got is None
    else:
        assert got == pytest.approx(want, abs=1e-9)


@given(st.lists(st.tuples(st.integers(0, 2), st.integers(0, 2)), min_size=1, max_size=30))
@settings(max_examples=100, deadline=None)
def test_alpha_two_coders_closed_form(pairs):
    n_units = len(pairs)
    n = 2 * n_units
    disagreements = sum(x != y for x, y in pairs)
    counts = {}
    for x, y in pairs:
        counts[x] = counts.get(x, 0) + 1
        counts[y] = counts.get(y, 0) + 1
    denom = n**2 - sum(c * c for c in counts.values())
    got = krippendorff_alpha_nominal([list(p) for p in pairs])
    if denom == 0:
        assert got is None
    else:
        assert got == pytest.approx(1 - (n - 1) * 2 * disagreements / denom, abs=1e-9)
