"""Budget, cache and refusal contract of §7.3/§7.4, parametrized over Env implementations.

Each factory returns a `Case`: an Env plus the handles that play each role in the rules below. The table double and
the T11 broker (on a real toy contrast) must pass the same suite.
"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

from habench.env.broker import BrokerEnv
from habench.env.table import TableEnv, single_key_replay
from habench.methods.base import INADMISSIBLE, NO_REPLAY, BudgetExhausted, Env, Unavailable, presence
from habench.oracle import toy
from habench.oracle.contrast import make_contrast
from habench.pipeline.catalog import V1
from habench.types import SYSTEM_ICD10_WHO, AssocKey, Presence
from habench.views.layout import BrokerSide, Entry, Manifest

KEY = AssocKey(1, SYSTEM_ICD10_WHO, "hier:toy", "C61")


@dataclass(frozen=True)
class Case:
    env: Env
    handles: frozenset[str]  # every evaluable handle
    a: str  # alone, it makes the query present
    b: str  # another admissible, non-inert handle
    inert: str  # realizes the same run with and without it
    prep: str  # a prep handle: R-B refuses every set with it
    bad: frozenset[str]  # an inadmissible set
    key: AssocKey
    finals: tuple[Presence, Presence]  # observed x0 and x1 presence of `key`


def table_env(capability="R-A", budget=None, *, tmp_path: Path | None = None) -> Case:
    handles = ("ent_thr", "icd_thr", "trait", "ev:prep0")
    env = TableEnv(
        handles=handles,
        replay=single_key_replay(KEY, [{"ent_thr"}, {"ent_thr", "icd_thr"}], Presence.ABSENT, Presence.PRESENT),
        capability_=capability,
        budget=budget,
        inadmissible=frozenset({frozenset({"ev:prep0"})}),
        inert=frozenset({"trait"}),
        rb_refused=frozenset({"ev:prep0"}),
    )
    # the replay of D = all handles is not a listed sufficient set, so the table's own finals are ABSENT, ABSENT
    return Case(env, frozenset(handles), "ent_thr", "icd_thr", "trait", "ev:prep0", frozenset({"ev:prep0"}), KEY,
                (Presence.ABSENT, Presence.ABSENT))


def broker_env(capability="R-A", budget=None, *, tmp_path: Path) -> Case:
    """A real toy contrast: ent_thr and icd_thr move, two prep factors (only the pair is stored) and a declared-only
    `trait` (d0 trait differs from the executed one), which the code link makes inert."""
    med = 900_000_001
    hier = toy.hierarchy()
    x1 = V1.with_(ent_thr=0.55, icd_thr=0.55)
    contrast = make_contrast(
        "c", "g", [med], "who", V1, x1, d0=V1.with_(trait="v1_hyp_le_0.6"), d1=x1,
        prep=["dup_ind", "mask_drug"], prep_available=[["dup_ind", "mask_drug"]], check_sealed=False,
    )
    evidence = toy.evidence({med: toy.response([toy.entity(1, 0.58, [("C61", 0.9)])])})
    view = tmp_path / "view"
    view.mkdir(exist_ok=True)
    (view / "manifest.json").write_text(Manifest("v1", (Entry("a1", "acm_response", "x0", "00"),)).to_json())
    side = BrokerSide("v1", "dev", "c", "L2-R", ())
    env = BrokerEnv(side, contrast, evidence, hier, view, capability, budget,
                    prep_evidence={("dup_ind", "mask_drug"): evidence})
    key = AssocKey(med, SYSTEM_ICD10_WHO, hier.version, "C61")
    handles = frozenset(env.factors())
    assert handles == {"ent_thr", "icd_thr", "trait", "dup_ind", "mask_drug"}
    return Case(env, handles, "ent_thr", "icd_thr", "trait", "dup_ind", frozenset({"dup_ind"}), key,
                (Presence.ABSENT, Presence.PRESENT))


ENV_FACTORIES: list[Callable[..., Case]] = [table_env, broker_env]


@pytest.fixture(params=ENV_FACTORIES, ids=lambda f: f.__name__)
def make(request, tmp_path):
    def build(**kw) -> Case:
        return request.param(tmp_path=tmp_path, **kw)

    return build


def test_empty_and_full_count(make):
    c = make()
    c.env.evaluate(frozenset())
    c.env.evaluate(c.handles)
    assert c.env.meter().evaluations == 2


def test_repeat_is_free(make):
    c = make(budget=1)
    r1 = c.env.evaluate(frozenset({c.a}))
    r2 = c.env.evaluate(frozenset({c.a}))
    assert r1 == r2 and c.env.meter().evaluations == 1


def test_inert_handles_stripped_before_cache(make):
    c = make(budget=1)
    a = c.env.evaluate(frozenset({c.a}))
    b = c.env.evaluate(frozenset({c.a, c.inert}))
    assert a == b and c.env.meter().evaluations == 1


def test_inadmissible_costs_nothing(make):
    c = make()
    with pytest.raises(Unavailable) as e:
        c.env.evaluate(c.bad)
    assert e.value.reason == INADMISSIBLE
    assert c.env.meter().evaluations == 0


def test_rc_refuses_everything(make):
    c = make(capability="R-C")
    for s in (frozenset(), frozenset({c.a})):
        with pytest.raises(Unavailable) as e:
            c.env.evaluate(s)
        assert e.value.reason == NO_REPLAY
    assert c.env.meter().evaluations == 0


def test_rb_refuses_prep(make):
    c = make(capability="R-B")
    with pytest.raises(Unavailable) as e:
        c.env.evaluate(frozenset({c.prep, c.a}))
    assert e.value.reason == NO_REPLAY
    assert c.env.evaluate(frozenset({c.a})).state(c.key) == Presence.PRESENT
    assert c.env.meter().evaluations == 1


def test_unknown_handle_is_value_error(make):
    c = make(budget=0)
    with pytest.raises(ValueError):
        c.env.evaluate(frozenset({"nope"}))
    assert c.env.meter().evaluations == 0


def test_budget_exhausted(make):
    c = make(budget=2)
    c.env.evaluate(frozenset())
    c.env.evaluate(frozenset({c.a}))
    with pytest.raises(BudgetExhausted):
        c.env.evaluate(frozenset({c.b}))
    assert c.env.meter().evaluations == 2
    c.env.evaluate(frozenset({c.a}))  # cached sets stay free after exhaustion


def test_finals_are_free(make):
    c = make(budget=0)
    assert (presence(c.env.final("x0"), c.key), presence(c.env.final("x1"), c.key)) == c.finals
    assert c.env.meter().evaluations == 0
