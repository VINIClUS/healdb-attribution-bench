"""Budget, cache and refusal contract of §7.3/§7.4, parametrized over Env implementations.

The T11 broker joins `ENV_FACTORIES` and must pass the same suite.
"""

from collections.abc import Callable

import pytest

from habench.env.table import TableEnv, single_key_replay
from habench.methods.base import INADMISSIBLE, NO_REPLAY, BudgetExhausted, Env, Unavailable
from habench.types import SYSTEM_ICD10_WHO, AssocKey, Presence

KEY = AssocKey(1, SYSTEM_ICD10_WHO, "hier:toy", "C61")
HANDLES = ("ent_thr", "icd_thr", "trait", "ev:prep0")


def table_env(capability="R-A", budget=None, inadmissible=(), inert=(), rb_refused=("ev:prep0",)) -> Env:
    return TableEnv(
        handles=HANDLES,
        replay=single_key_replay(KEY, [{"ent_thr"}, {"ent_thr", "icd_thr"}], Presence.ABSENT, Presence.PRESENT),
        capability_=capability,
        budget=budget,
        inadmissible=frozenset(frozenset(s) for s in inadmissible),
        inert=frozenset(inert),
        rb_refused=frozenset(rb_refused),
    )


ENV_FACTORIES: list[Callable[..., Env]] = [table_env]


@pytest.fixture(params=ENV_FACTORIES, ids=lambda f: f.__name__)
def make(request):
    return request.param


def test_empty_and_full_count(make):
    env = make()
    env.evaluate(frozenset())
    env.evaluate(frozenset(HANDLES))
    assert env.meter().evaluations == 2


def test_repeat_is_free(make):
    env = make(budget=1)
    r1 = env.evaluate(frozenset({"ent_thr"}))
    r2 = env.evaluate(frozenset({"ent_thr"}))
    assert r1 == r2 and env.meter().evaluations == 1


def test_inert_handles_stripped_before_cache(make):
    env = make(inert=("trait",), budget=1)
    a = env.evaluate(frozenset({"ent_thr"}))
    b = env.evaluate(frozenset({"ent_thr", "trait"}))
    assert a == b and env.meter().evaluations == 1


def test_inadmissible_costs_nothing(make):
    env = make(inadmissible=[{"icd_thr"}])
    with pytest.raises(Unavailable) as e:
        env.evaluate(frozenset({"icd_thr"}))
    assert e.value.reason == INADMISSIBLE
    assert env.meter().evaluations == 0


def test_rc_refuses_everything(make):
    env = make(capability="R-C")
    for s in (frozenset(), frozenset({"ent_thr"})):
        with pytest.raises(Unavailable) as e:
            env.evaluate(s)
        assert e.value.reason == NO_REPLAY
    assert env.meter().evaluations == 0


def test_rb_refuses_prep(make):
    env = make(capability="R-B")
    with pytest.raises(Unavailable) as e:
        env.evaluate(frozenset({"ev:prep0", "ent_thr"}))
    assert e.value.reason == NO_REPLAY
    assert env.evaluate(frozenset({"ent_thr"})).state(KEY) == Presence.PRESENT
    assert env.meter().evaluations == 1


def test_unknown_handle_is_value_error(make):
    env = make(budget=0)
    with pytest.raises(ValueError):
        env.evaluate(frozenset({"nope"}))
    assert env.meter().evaluations == 0


def test_budget_exhausted(make):
    env = make(budget=2)
    env.evaluate(frozenset())
    env.evaluate(frozenset({"ent_thr"}))
    with pytest.raises(BudgetExhausted):
        env.evaluate(frozenset({"icd_thr"}))
    assert env.meter().evaluations == 2
    env.evaluate(frozenset({"ent_thr"}))  # cached sets stay free after exhaustion


def test_finals_are_free(make):
    env = make(budget=0)
    assert env.final("x0")[KEY] == Presence.ABSENT
    assert env.final("x1")[KEY] == Presence.ABSENT  # D = all handles is not a listed sufficient set
    assert env.meter().evaluations == 0
