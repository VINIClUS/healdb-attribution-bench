"""BugDoc adapter: upstream tests, paper Example 1, Theorems 1-5 on the vendored code, and the `Method` behaviour."""

from __future__ import annotations

import logging
import os
import random
import subprocess
import sys
from collections.abc import Callable
from itertools import combinations, product
from pathlib import Path

import pytest
from hypothesis import HealthCheck, assume, example, given, settings
from hypothesis import strategies as st

from habench.env.table import TableEnv, single_key_replay
from habench.methods.base import CAPABILITIES, Query, validated
from habench.methods.bugdoc_adapter import _BUGDOC_ROOT, BugDocMethod, run_bugdoc  # also puts bugdoc on sys.path
from habench.types import SYSTEM_ICD10_WHO, AssocKey, OutputState, Presence

from bugdoc.algos.stacked_shortcut_standalone import StackedShortcutStandalone  # noqa: E402  isort: skip

REPO = Path(__file__).resolve().parents[1]
KEY = AssocKey(1, SYSTEM_ICD10_WHO, "hier:toy", "C61")
Q = Query("q1", KEY)


@pytest.fixture(autouse=True)
def _quiet_bugdoc():
    previous = logging.root.manager.disable
    logging.disable(logging.CRITICAL)  # upstream logs whole histories at DEBUG
    yield
    logging.disable(previous)


# 1. Upstream tests --------------------------------------------------------------------------------------------------


def _upstream(name: str, tmp_path: Path) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PYTHONPATH": str(_BUGDOC_ROOT), "PYTHONDONTWRITEBYTECODE": "1"}
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-c", os.devnull,
         f"--rootdir={tmp_path}", str(_BUGDOC_ROOT / "upstream_tests" / name)],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=300,
    )


def test_upstream_standalone_tests_pass(tmp_path):
    before = sorted(p.name for p in REPO.iterdir())
    res = _upstream("test_standalone.py", tmp_path)
    assert res.returncode == 0, res.stdout + res.stderr
    assert sorted(p.name for p in REPO.iterdir()) == before
    # upstream test_algorithm_execution creates the file named by its entry_point in the cwd: confined to tmp_path
    assert {q.name for q in tmp_path.rglob("*")} <= {"entry_point"}


@pytest.mark.xfail(
    strict=True,
    reason="upstream budget_test.py needs zmq, a python_worker.py and a .vt file that are not vendored "
    "(it targets DebuggingDecisionTrees in ZMQ mode, which this benchmark does not use)",
)
def test_upstream_budget_test_needs_zmq(tmp_path):
    res = _upstream("budget_test.py", tmp_path)
    assert res.returncode == 0, res.stdout + res.stderr


# 2. Paper Example 1 -------------------------------------------------------------------------------------------------

SPACE = {
    "Dataset": ["Iris", "Digits"],
    "Estimator": ["Logistic Regression", "Decision Tree", "Gradient Boosting"],
    "LibraryVersion": ["1.0", "2.0"],
}


def _history(rows):
    return [[list(r) for r in rows], [list(r) for r in rows]]  # allexperiments and allresults are separate lists


def test_paper_example_1():
    calls: list[dict[str, str]] = []

    def evaluation(params):
        calls.append(dict(params))
        return params["LibraryVersion"] != "2.0"  # True = succeed; consistent with every row of Table 2

    table1 = [
        ["Iris", "Logistic Regression", "1.0", True],
        ["Digits", "Decision Tree", "1.0", True],
        ["Iris", "Gradient Boosting", "2.0", False],
    ]
    algo = StackedShortcutStandalone(k=4, max_iter=1000, function=evaluation)
    causes = algo.run("unused", SPACE, outputs=["result"], historical_runs=_history(table1))
    assert causes == [[(2, "2.0")]]  # {LibraryVersion=2.0}
    # Table 2 lists 3 new rows; the last one (Digits/DT/1.0) duplicates CPg. The code looks a candidate up in the
    # history before executing it (`cf_aux not in self.expers`), so it is NOT executed: 2 executions, as with
    # memoisation in the paper's counting.
    assert calls == [
        {"Dataset": "Digits", "Estimator": "Gradient Boosting", "LibraryVersion": "2.0"},
        {"Dataset": "Digits", "Estimator": "Decision Tree", "LibraryVersion": "2.0"},
    ]


# 3. Theorems 1-5 (property tests on synthetic DNF pipelines) ---------------------------------------------------------

Literal = tuple[int, int]


def _minimal_definitive(fails: Callable[[tuple[int, ...]], bool], n: int, m: int) -> tuple[set[frozenset[Literal]], Callable[[frozenset[Literal]], bool]]:
    instances = list(product(range(m), repeat=n))
    failing = {i: fails(i) for i in instances}
    memo: dict[frozenset[Literal], bool] = {}

    def definitive(conj: frozenset[Literal]) -> bool:
        if conj not in memo:
            memo[conj] = all(failing[i] for i in instances if all(i[p] == v for p, v in conj))
        return memo[conj]

    minimal: set[frozenset[Literal]] = set()
    for values in product(range(-1, m), repeat=n):
        conj = frozenset((p, v) for p, v in enumerate(values) if v >= 0)
        if conj and definitive(conj) and not any(definitive(conj - {lit}) for lit in conj if conj - {lit}):
            minimal.add(conj)
    return minimal, definitive


def _fails_from(terms) -> Callable[[tuple[int, ...]], bool]:
    return lambda i: any(all(i[p] == v for p, v in t) for t in terms)


@st.composite
def pipelines(draw, k: int, singletons: bool = False):
    """n params, k+1 values each; instances 0 (CPf) and 1..k (goods) are mutually disjoint by construction."""
    n = draw(st.integers(3, 5))
    m = k + 1
    perms = [draw(st.permutations(range(m))) for _ in range(n)]
    instances = [tuple(perms[p][j] for p in range(n)) for j in range(m)]
    size = st.just(1) if singletons else st.integers(1, n)
    terms = draw(
        st.lists(
            size.flatmap(lambda s: st.lists(st.tuples(st.integers(0, n - 1), st.integers(0, m - 1)), min_size=s, max_size=s, unique_by=lambda t: t[0])),
            min_size=1,
            max_size=3,
        )
    )

    fails = _fails_from(terms)
    cpf, goods = instances[0], instances[1:]
    assume(fails(cpf) and not any(fails(g) for g in goods))
    return n, m, fails, cpf, goods


def _run(n: int, fails, cpf, goods, k: int):
    names = [f"p{i}" for i in range(n)]
    space = {nm: list(range(4)) for nm in names}

    def evaluation(params):
        return not fails(tuple(params[nm] for nm in names))

    rows = [[*cpf, False], *[[*g, True] for g in goods]]
    algo = StackedShortcutStandalone(k=k, max_iter=1000, function=evaluation)
    raw = algo.run("unused", space, outputs=["result"], historical_runs=_history(rows))
    return [frozenset(conj) for conj in raw]


PROP = settings(
    max_examples=int(os.environ.get("HAB_BUGDOC_EXAMPLES", "60")),
    deadline=None,
    derandomize=True,
    suppress_health_check=list(HealthCheck),
)


@PROP
@given(pipelines(k=1, singletons=True))
def test_theorem_1_singleton_causes_assert_a_minimal_definitive_cause(p):
    n, m, fails, cpf, goods = p
    minimal, _ = _minimal_definitive(fails, n, m)
    assume(all(len(c) == 1 for c in minimal))
    asserted = _run(n, fails, cpf, goods, k=1)
    assert len(asserted) == 1 and asserted[0] in minimal


@PROP
@given(pipelines(k=1))
def test_theorem_2_never_asserts_a_strict_superset_of_a_minimal_cause(p):
    n, m, fails, cpf, goods = p
    minimal, _ = _minimal_definitive(fails, n, m)
    for a in _run(n, fails, cpf, goods, k=1):
        assert not any(mc < a for mc in minimal)


# Counterexample found by hypothesis (1500 examples) on the vendored code: k=2, 5 params with 3 values, failure =
# (p0=0) or (p0=1 and p2=2), CPf=(0,0,2,0,0), goods (1,1,1,1,1) and (2,2,0,2,2). Against good #1 Shortcut adopts
# p0=1 (the second cause, contained in CPf u CPg, keeps failing) and asserts the truncated {p2=2}. The union of
# Algorithm 2 keeps that assertion, so Theorem 5 read as "every asserted conjunction is definitive" fails even
# for the paper's pseudo-code; the proof only shows that at least one assertion is not truncated (next test).
_T5_COUNTEREXAMPLE = (
    2,
    (5, 3, _fails_from([[(0, 0)], [(0, 1), (2, 2)]]), (0, 0, 2, 0, 0), [(1, 1, 1, 1, 1), (2, 2, 0, 2, 2)]),
)


@pytest.mark.xfail(
    strict=True,
    reason="truncated {p2=2} asserted: k=2, causes (p0=0) | (p0=1,p2=2), CPf=(0,0,2,0,0), "
    "goods (1,1,1,1,1),(2,2,0,2,2); Thm 5 as 'no truncated assertion' does not hold (paper's union keeps it too)",
)
@example(_T5_COUNTEREXAMPLE)
@PROP
@given(st.integers(1, 2).flatmap(lambda k: st.tuples(st.just(k), pipelines(k=k))))
def test_theorem_5_every_assertion_is_definitive(p):
    k, (n, m, fails, cpf, goods) = p
    minimal, definitive = _minimal_definitive(fails, n, m)
    assume(len(minimal) <= k)
    for a in _run(n, fails, cpf, goods, k=k):
        assert definitive(a), f"truncated assertion {sorted(a)}; minimal causes {sorted(map(sorted, minimal))}"


@pytest.mark.xfail(
    strict=True,
    reason="code deviates from Algorithm 2: cf is not reset to CPf between good instances. Same counterexample: "
    "after good #1 cf=(1,1,2,1,1) and it never returns to p0=0, so both passes assert only the truncated {p2=2}; "
    "the paper's reset would yield {p0=0} on the second pass",
)
@example(_T5_COUNTEREXAMPLE)
@PROP
@given(st.integers(1, 2).flatmap(lambda k: st.tuples(st.just(k), pipelines(k=k))))
def test_theorem_5_some_assertion_is_definitive(p):
    k, (n, m, fails, cpf, goods) = p
    minimal, definitive = _minimal_definitive(fails, n, m)
    assume(len(minimal) <= k)
    asserted = _run(n, fails, cpf, goods, k=k)
    assert any(definitive(a) for a in asserted), f"asserted {asserted}; minimal {minimal}"


# 4. Adapter on TableEnv ---------------------------------------------------------------------------------------------

D3 = ("ent_thr", "patch", "icd_thr")


def _env(sufficient, handles=D3, **kw) -> TableEnv:
    return TableEnv(handles=handles, replay=single_key_replay(KEY, sufficient, Presence.ABSENT, Presence.PRESENT), **kw)


def _powerset(handles):
    return [frozenset(c) for r in range(len(handles) + 1) for c in combinations(handles, r)]


def _is_sufficient(env_sets, s) -> bool:
    return frozenset(s) in env_sets


def test_ex07_shape_returns_antichain_of_sufficient_sets():
    sufficient = [s for s in _powerset(D3) if {"ent_thr", "patch"} & s]
    env = _env(sufficient)
    out = BugDocMethod().explain(env, [Q])["q1"]
    assert out == validated(out)
    assert out.state == OutputState.EXPLICACAO_VERIFICADA
    (family,) = out.families
    assert all(frozenset(s) in set(sufficient) for s in family)
    # Observed behaviour: flips ent_thr (still reproduces x1), keeps patch, flips icd_thr -> {patch}. BugDoc finds
    # one sufficient set, not the whole family {{ent_thr},{patch}}.
    assert family == (("patch",),)
    # Certificates: finals for ∅ and D, eval for exactly the sets BugDoc evaluated through the Env.
    finals = [c for c in out.certificates if c.kind == "final"]
    assert {(c.subject, c.value) for c in finals} == {((), False), (tuple(sorted(D3)), True)}
    evals = {frozenset(c.subject): c.value for c in out.certificates if c.kind == "eval"}
    assert evals == {frozenset(s): frozenset(s) in set(sufficient) for s in env.log}
    assert len(evals) == env.meter().evaluations


def test_single_factor_case():
    env = _env([{"f"}], handles=("f",))
    out = BugDocMethod().explain(env, [Q])["q1"]
    assert out.state == OutputState.EXPLICACAO_VERIFICADA
    assert out.families == ((("f",),),)
    assert env.meter().evaluations == 0  # all-x0 / all-x1 are the free observed finals


def test_unchanged_query_is_absence_of_change():
    env = _env([], finals={"x0": {KEY: Presence.ABSENT}, "x1": {KEY: Presence.ABSENT}})
    out = BugDocMethod().explain(env, [Q])["q1"]
    assert out.state == OutputState.AUSENCIA_DE_MUDANCA and out.families == ()
    assert env.meter().evaluations == 0


def test_rc_capability_is_insufficient_information():
    env = _env([{"f"}], handles=("f",), capability_="R-C")
    out = BugDocMethod().explain(env, [Q])["q1"]
    assert (out.state, out.reason) == (OutputState.INFORMACAO_INSUFICIENTE, "output_diff_only")
    assert env.meter().evaluations == 0


def test_budget_two_stops_the_run():
    sufficient = [s for s in _powerset(D3) if {"ent_thr", "patch"} & s]
    env = _env(sufficient, budget=2)
    out = BugDocMethod().explain(env, [Q])["q1"]
    assert out == validated(out)
    assert out.state in (OutputState.ORCAMENTO_ESGOTADO, OutputState.EXPLICACAO_VERIFICADA)
    assert out.state == OutputState.ORCAMENTO_ESGOTADO and out.reason == "orcamento"  # needs 3 distinct sets here
    assert env.meter().evaluations <= 2


def test_inadmissible_sets_are_could_not_run():
    # Every hybrid BugDoc would try is inadmissible: nothing evaluates, nothing is asserted beyond D.
    sufficient = [s for s in _powerset(D3) if {"ent_thr", "patch"} & s]
    env = _env(sufficient, inadmissible=frozenset(s for s in _powerset(D3) if 0 < len(s) < 3))
    out = BugDocMethod().explain(env, [Q])["q1"]
    assert out == validated(out)
    assert out.state == OutputState.EXPLICACAO_VERIFICADA
    assert out.families == ((tuple(sorted(D3)),),)  # D itself: BugDoc could not shrink it
    assert env.meter().evaluations == 0


def test_no_files_and_random_state_untouched(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    before_repo = sorted(p.name for p in REPO.iterdir())
    random.seed(1234)
    state = random.getstate()
    sufficient = [s for s in _powerset(D3) if "patch" in s]
    a = run_bugdoc(_env(sufficient), KEY, Presence.PRESENT, seed=7)
    assert random.getstate() == state
    b = run_bugdoc(_env(sufficient), KEY, Presence.PRESENT, seed=7)
    assert a == b and a.causes == (frozenset({"patch"}),)
    assert not list(tmp_path.iterdir())
    assert sorted(p.name for p in REPO.iterdir()) == before_repo


@pytest.mark.parametrize("cap", CAPABILITIES)
def test_output_always_valid_and_shared_env(cap):
    sufficient = [s for s in _powerset(D3) if {"ent_thr", "icd_thr"} <= s]
    env = _env(sufficient, capability_=cap)
    qs = [Query("a", KEY), Query("b", KEY)]
    out = BugDocMethod().explain(env, qs)
    assert set(out) == {"a", "b"}
    assert all(e == validated(e) for e in out.values())
    if cap != "R-C":
        assert out["a"].families == out["b"].families  # same run twice; the second is served by the Env cache
