"""SPEC §6.3 reference BFS: spec examples plus properties against a naive O(3^n) reference."""

import json
from itertools import combinations
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from habench.env.table import TableEnv, single_key_replay
from habench.methods.base import BudgetExhausted, EvalResult, Unavailable
from habench.methods.search import SearchResult, bfs
from habench.types import SYSTEM_ICD10_WHO, AssocKey, Presence

EXAMPLES = json.loads((Path(__file__).parent / "data" / "spec_examples.json").read_text())["examples"]
KEY = AssocKey(1, SYSTEM_ICD10_WHO, "hier:toy", "C61")


def _cases(ex_id: str):
    ex = next(e for e in EXAMPLES if e["id"] == ex_id)
    for i, case in enumerate(ex["cases"]):
        merged = {**ex, **case}
        yield pytest.param(merged, id=f"{ex_id}-{case.get('name', i)}")


def _fam(f) -> tuple[tuple[str, ...], ...]:
    return tuple(tuple(s) for s in f)


@pytest.mark.parametrize("case", [*_cases("EX-16"), *_cases("EX-28")])
def test_spec_examples(case):
    env = TableEnv(
        handles=case["D"],
        replay=single_key_replay(KEY, case["sufficient"], Presence.ABSENT, Presence.PRESENT),
        budget=case["budget"],
        inadmissible=frozenset(frozenset(s) for s in case.get("inadmissible", [])),
    )
    res = bfs(env.evaluate, case["D"], {"q": KEY})
    exp = case["expected"]
    assert env.meter().evaluations == exp["evaluations"]
    assert len(res.evaluated) == exp["evaluations"]
    if "evaluated_order" in exp:
        assert res.evaluated == tuple(frozenset(s) for s in exp["evaluated_order"])
    assert res.families["q"] == _fam(exp["family"])
    assert res.complete["q"] is exp["complete"]
    assert res.exhausted is (case["budget"] is not None)


def test_non_monotone_ex10_shape():
    D = ["ent_thr", "icd_thr", "patch:p3"]
    suff = [{"ent_thr"}, {"ent_thr", "patch:p3"}, set(D)]
    env = TableEnv(D, single_key_replay(KEY, suff, Presence.ABSENT, Presence.PRESENT))
    res = bfs(env.evaluate, D, {"q": KEY})
    assert res.families["q"] == (("ent_thr",),)
    assert res.complete["q"]


def test_unchanged_and_single_factor():
    env = TableEnv(["f"], single_key_replay(KEY, [{"f"}], Presence.ABSENT, Presence.PRESENT))
    other = AssocKey(2, SYSTEM_ICD10_WHO, "hier:toy", "C50")
    res = bfs(env.evaluate, ["f"], {"q": KEY, "u": other})
    assert res.families == {"q": (("f",),)} and res.complete == {"q": True}
    assert res.unchanged == frozenset({"u"})
    assert res.evaluated == (frozenset(), frozenset({"f"}))


def test_replay_failure_propagates():
    def boom(s):
        raise Unavailable("no_replay")

    with pytest.raises(Unavailable):
        bfs(boom, ["a", "b"], {"q": KEY})
    env = TableEnv(["a", "b"], single_key_replay(KEY, [{"a", "b"}], Presence.ABSENT, Presence.PRESENT), budget=1)
    with pytest.raises(BudgetExhausted):
        bfs(env.evaluate, ["a", "b"], {"q": KEY})


@given(st.data())
@settings(max_examples=200, deadline=None)
def test_matches_oracle_reference_bfs(data):
    """The method-side BFS and β's truth-side reference BFS agree on evaluations, families and completeness."""
    from habench.oracle.families import reference_bfs

    names, table, inad = data.draw(scenario())
    budget = data.draw(st.one_of(st.none(), st.integers(2, 2 ** len(names))))
    dummies = frozenset(data.draw(st.sets(st.sampled_from(sorted(true_dummies(table, names)))))) if true_dummies(table, names) else frozenset()
    env = env_for(table, names, budget=budget, inadmissible=inad)
    res = bfs(env.evaluate, names, {"q": KEY}, {"q": dummies})
    ref = reference_bfs(names, {"q": lambda s: table[s]}, budget=budget, admissible=lambda s: s not in inad,
                        dummies={"q": dummies})
    assert res.evaluated == ref.evaluated
    assert res.exhausted == ref.exhausted
    if "q" in ref.families:
        assert as_sets(res) == set(ref.families["q"])
        assert res.complete["q"] == ref.complete["q"]


# ---- property tests against a naive reference ----

Table = dict[frozenset[str], bool]


def subsets(names):
    return [frozenset(c) for k in range(len(names) + 1) for c in combinations(names, k)]


def naive(table: Table, inadmissible: frozenset[frozenset[str]], names) -> tuple[set[frozenset[str]], bool]:
    full = frozenset(names)
    adm_suff = [s for s in subsets(names) if s and s not in inadmissible and table[s] == table[full]]
    fam = {s for s in adm_suff if not any(t < s for t in adm_suff)}
    complete = all(any(t < s for t in adm_suff) for s in inadmissible)
    return fam, complete


def env_for(table: Table, names, budget=None, inadmissible=frozenset()):
    def replay(s):
        return EvalResult({KEY: Presence.PRESENT if table[s] else Presence.ABSENT}, ())

    return TableEnv(names, replay, budget=budget, inadmissible=inadmissible)


def true_dummies(table: Table, names) -> frozenset[str]:
    return frozenset(f for f in names if all(table[s | {f}] == table[s] for s in subsets(names) if f not in s))


@st.composite
def scenario(draw, n=None):
    n = n or draw(st.integers(1, 5))
    names = [f"f{i}" for i in range(n)]
    subs = subsets(names)
    bits = draw(st.lists(st.booleans(), min_size=len(subs), max_size=len(subs)))
    table = dict(zip(subs, bits, strict=True))
    full = frozenset(names)
    table[frozenset()] = draw(st.booleans())
    table[full] = not table[frozenset()]
    middle = [s for s in subs if s and s != full]
    inad = frozenset(draw(st.sets(st.sampled_from(middle)))) if middle else frozenset()
    return names, table, inad


def as_sets(res: SearchResult, q="q"):
    return {frozenset(s) for s in res.families[q]}


@given(scenario())
@settings(max_examples=300, deadline=None)
def test_matches_naive(sc):
    names, table, inad = sc
    env = env_for(table, names, inadmissible=inad)
    res = bfs(env.evaluate, names, {"q": KEY})
    fam, complete = naive(table, inad, names)
    assert as_sets(res) == fam
    assert res.complete["q"] == complete
    assert not res.exhausted
    assert len(res.evaluated) == env.meter().evaluations == len(set(res.evaluated))


@given(scenario(), st.data())
@settings(max_examples=300, deadline=None)
def test_dummy_pruning_keeps_family(sc, data):
    names, table, inad = sc
    # In the core, admissibility depends only on S ∩ prep (SPEC 5.3) and dummy rules never certify a prep factor
    # (SPEC 4.6 rule 0), so adding or removing a certified dummy never changes admissibility. Only such dummies
    # are realistic; others let pruning skip admissible supersets of inadmissible sets.
    dummies = frozenset(
        f for f in true_dummies(table, names)
        if all((s in inad) == ((s | {f}) in inad) for s in subsets(names) if f not in s)
    )
    chosen = frozenset(data.draw(st.sets(st.sampled_from(sorted(dummies))))) if dummies else frozenset()
    env = env_for(table, names, inadmissible=inad)
    res = bfs(env.evaluate, names, {"q": KEY}, {"q": chosen})
    fam, complete = naive(table, inad, names)
    assert as_sets(res) == fam and res.complete["q"] == complete
    plain = bfs(env_for(table, names, inadmissible=inad).evaluate, names, {"q": KEY})
    assert len(res.evaluated) <= len(plain.evaluated)


@given(scenario(), st.data())
@settings(max_examples=300, deadline=None)
def test_budget_limited(sc, data):
    names, table, inad = sc
    budget = data.draw(st.integers(2, max(2, 2 ** len(names))))
    env = env_for(table, names, budget=budget, inadmissible=inad)
    res = bfs(env.evaluate, names, {"q": KEY})
    assert as_sets(res) <= naive(table, inad, names)[0]
    assert env.meter().evaluations <= budget
    if res.exhausted:
        assert res.complete["q"] is False


@given(st.integers(1, 5), st.integers(2, 3), st.data())
@settings(max_examples=200, deadline=None)
def test_multi_query_joint(n, nq, data):
    names = [f"f{i}" for i in range(n)]
    tables = [data.draw(scenario(n))[1] for _ in range(nq)]
    keys = {f"q{i}": AssocKey(i, SYSTEM_ICD10_WHO, "hier:toy", f"C{i}") for i in range(nq)}

    def replay(s):
        return EvalResult(
            {keys[f"q{i}"]: Presence.PRESENT if t[s] else Presence.ABSENT for i, t in enumerate(tables)}, ()
        )

    env = TableEnv(names, replay)
    res = bfs(env.evaluate, names, keys)
    assert env.meter().evaluations <= 2**n
    for i, t in enumerate(tables):
        q = f"q{i}"
        assert as_sets(res, q) == naive(t, frozenset(), names)[0]
        assert res.complete[q]
