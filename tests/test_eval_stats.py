import numpy as np
import pytest
from hypothesis import given, strategies as st
from scipy.stats import binomtest

from habench.eval.stats import (
    clopper_pearson_lower,
    clopper_pearson_upper,
    committed_risk,
    coverage,
    h1b_guard,
    holm,
    ni_pvalue,
    noninferiority,
    p_h2,
    paired_cluster_bootstrap,
    selective_risk,
    stability_check,
    sup_pvalue,
)

PVALS = st.lists(st.floats(0.0, 1.0), min_size=1, max_size=6)


def test_ex18():
    assert holm([0.004, 0.03, 1.0]) == [True, False, False]
    assert holm([0.001, 0.011, 0.02]) == [True, True, True]
    assert holm([0.02, 0.001, 0.011]) == [True, True, True]


def _brute_holm(p, alpha):
    m = len(p)
    out = [False] * m
    for k in range(m):
        ok = all(sorted(p)[j] <= alpha / (m - j) for j in range(k + 1))
        if ok:
            target = sorted(range(m), key=lambda i: p[i])[k]
            out[target] = True
    return out


@given(PVALS, st.floats(0.001, 0.2))
def test_holm_properties(p, alpha):
    r = holm(p, alpha)
    m = len(p)
    assert r == _brute_holm(p, alpha)
    bonf = [x <= alpha / m for x in p]
    unadj = [x <= alpha for x in p]
    assert all(r[i] for i in range(m) if bonf[i])
    assert all(unadj[i] for i in range(m) if r[i])


def test_ex20():
    d = [-0.03] * 2 + [0.0] * 7
    assert ni_pvalue(d) == pytest.approx(0.3)
    assert ni_pvalue([0.0] * 19) == pytest.approx(0.05)
    assert ni_pvalue([0.0] * 19) > 0.025


@given(st.lists(st.floats(-0.2, 0.2), min_size=1, max_size=200))
def test_pvalue_properties(d):
    B = len(d)
    p_ni, p_sup = ni_pvalue(d), sup_pvalue(d)
    assert p_ni >= 1 / (B + 1) and p_sup >= 1 / (B + 1)
    assert p_ni <= p_sup <= 1.0  # margin -0.02 < 0
    assert ni_pvalue(d, -0.05) <= ni_pvalue(d, -0.01)


def test_p_h2():
    assert p_h2(0.01, 0.2) == 0.2


def test_ex19_and_zero():
    assert clopper_pearson_upper(0, 40, 0.025) == pytest.approx(0.0880973, abs=1e-7)
    assert clopper_pearson_upper(0, 40, 0.025) == pytest.approx(1 - 0.025 ** (1 / 40))
    assert clopper_pearson_upper(5, 5) == 1.0
    assert clopper_pearson_lower(0, 5) == 0.0


@pytest.mark.parametrize("n", [1, 7, 40, 200])
@pytest.mark.parametrize("alpha", [0.025, 0.05])
def test_clopper_pearson_vs_scipy(n, alpha):
    for k in sorted({0, 1, n // 2, max(n - 1, 0)}):
        ci = binomtest(k, n).proportion_ci(confidence_level=1 - 2 * alpha, method="exact")
        assert clopper_pearson_upper(k, n, alpha) == pytest.approx(ci.high, abs=1e-9)
        assert clopper_pearson_lower(k, n, alpha) == pytest.approx(ci.low, abs=1e-9)


def test_invalid_counts():
    with pytest.raises(ValueError):
        clopper_pearson_upper(3, 2)


def _mean(gs):
    return float(np.mean(gs))


def test_bootstrap_deterministic_and_paired():
    groups = [0.1, -0.2, 0.3, 0.0, 0.05, 0.4]
    a = paired_cluster_bootstrap(groups, _mean, B=200)
    b = paired_cluster_bootstrap(groups, _mean, B=200)
    c = paired_cluster_bootstrap(groups, _mean, B=200, seed=1)
    assert a.B == 200
    assert np.array_equal(a.replicates, b.replicates)
    assert not np.array_equal(a.replicates, c.replicates)
    assert a.estimate == pytest.approx(np.mean(groups))
    lo, hi = a.ci()
    assert lo <= a.estimate <= hi
    assert a.lower(2.5) == lo and a.upper(97.5) == hi
    assert not a.identity_by_construction


def test_identity_by_construction():
    res = paired_cluster_bootstrap([0.0] * 10, _mean, B=50)
    assert res.identity_by_construction
    ni = noninferiority(res)
    assert ni.pvalue == pytest.approx(1 / 51)
    assert not ni.reject
    assert ni.note == "identidade por construção"


def test_noninferiority_rejects():
    res = paired_cluster_bootstrap([0.05, 0.06, 0.04, 0.05] * 5, _mean, B=500)
    ni = noninferiority(res)
    assert ni.reject and not ni.identity_by_construction and ni.note == ""
    assert ni.pvalue == pytest.approx(1 / 501)


def test_stability_check():
    groups = [float(x) for x in np.random.default_rng(0).normal(0, 0.1, 30)]
    tight = stability_check(groups, _mean, B=300, tol=10.0)
    assert tight.stable and tight.recommended_B == 300
    loose = stability_check(groups, _mean, B=300, tol=0.0)
    assert not loose.stable and loose.recommended_B == 10000
    assert loose.max_shift > 0 and len(loose.intervals) == 3


def test_coverage_and_risks():
    assert coverage(["correto_sustentado", "falha", "errado", "correto_sustentado"]) == 0.5
    assert coverage([]) == 0.0
    pairs = [
        ("explicacao_verificada", "correto_sustentado"),
        ("explicacao_verificada", "errado"),
        ("alternativas", "nao_comprometido"),
        ("ausencia_de_mudanca", "indevidamente_exclusivo"),
        ("informacao_insuficiente", "errado"),  # not categorical
        ("falha_de_execucao", "falha"),
    ]
    assert selective_risk(pairs) == pytest.approx(2 / 4)
    assert committed_risk(pairs) == pytest.approx(2 / 3)


def test_risks_empty_denominators():
    assert selective_risk([]) == 0.0
    assert committed_risk([]) == 0.0
    only_alt = [("alternativas", "nao_comprometido")]
    assert selective_risk(only_alt) == 0.0
    assert committed_risk(only_alt) == 0.0


def test_h1b_guard_percentile():
    d = [0.0] * 97 + [0.05] * 3  # 97.5th percentile is 0.05 -> fails
    assert not h1b_guard(d)
    d = [0.0] * 98 + [0.05] * 2  # 97.5th percentile is 0.0 -> passes
    assert h1b_guard(d)
    assert h1b_guard([0.02] * 10)
    assert not h1b_guard([0.0201] * 10)
