from habench.env.table import TableEnv, single_key_replay
from habench.methods.b0 import B0
from habench.methods.b1 import B1
from habench.methods.b3 import B3
from habench.methods.base import EvalResult, Query
from habench.types import SYSTEM_ICD10_WHO, AssocKey, OutputState, Presence

A = AssocKey(1, SYSTEM_ICD10_WHO, "hier:toy", "C61")
B = AssocKey(1, SYSTEM_ICD10_WHO, "hier:toy", "E119")
V = OutputState.EXPLICACAO_VERIFICADA


def ex07_env(**kw) -> TableEnv:
    """EX-07: sufficient = every S containing ent_thr or the patch."""
    D = ("ent_thr", "ev:p1", "icd_thr")
    suff = [s for s in _subsets(D) if {"ent_thr", "ev:p1"} & s]
    kw.setdefault("configs", {"x0": {"ent_thr": "0.60", "icd_thr": "0.60"}, "x1": {"ent_thr": "0.58", "icd_thr": "0.55"}})
    return TableEnv(handles=D, replay=single_key_replay(A, suff, Presence.ABSENT, Presence.PRESENT), **kw)


def _subsets(D):
    return [frozenset(c for i, c in enumerate(D) if m >> i & 1) for m in range(1 << len(D))]


def two_keys(s: frozenset[str]) -> EvalResult:
    return EvalResult({A: Presence.PRESENT if "ent_thr" in s else Presence.ABSENT, B: Presence.PRESENT}, ())


def test_b0():
    env = TableEnv(handles=("ent_thr",), replay=two_keys)
    out = B0().explain(env, [Query("a", A), Query("b", B)])
    assert out["a"].state == OutputState.INFORMACAO_INSUFICIENTE and out["a"].reason == "output_diff_only"
    assert out["b"].state == OutputState.AUSENCIA_DE_MUDANCA
    assert env.meter().evaluations == 0


def test_b1_declared_diff():
    out = B1().explain(ex07_env(), [Query("a", A)])
    assert out["a"].state == OutputState.ALTERNATIVAS
    assert out["a"].families == ((("ent_thr",),), (("icd_thr",),))
    one = ex07_env(configs={"x0": {"ent_thr": "0.60"}, "x1": {"ent_thr": "0.58"}})
    assert B1().explain(one, [Query("a", A)])["a"].families == ((("ent_thr",),),)
    none = ex07_env(configs={"x0": {}, "x1": {}})
    assert B1().explain(none, [Query("a", A)])["a"].state == OutputState.INFORMACAO_INSUFICIENTE


def test_b3_ex07_sufficient_singletons():
    env = ex07_env()
    out = B3().explain(env, [Query("a", A)])["a"]
    assert out.state == V and out.families == ((("ent_thr",), ("ev:p1",)),)
    assert env.meter().evaluations == 2 + 3 + 3
    assert {(c.kind, c.subject, c.value) for c in out.certificates} >= {
        ("final", (), False),
        ("eval", ("ent_thr",), True),
        ("eval", ("icd_thr",), False),
    }


def test_b3_interaction_reports_d():
    D = ("ent_thr", "icd_thr")
    env = TableEnv(handles=D, replay=single_key_replay(A, [set(D)], Presence.ABSENT, Presence.PRESENT))
    out = B3().explain(env, [Query("a", A)])["a"]
    assert out.state == V and out.families == ((("ent_thr", "icd_thr"),),)


def test_b3_pair_inside_larger_d_is_ambiguous():
    D = ("a1", "a2", "a3")
    suff = [{"a1", "a2"}, set(D)]
    env = TableEnv(handles=D, replay=single_key_replay(A, suff, Presence.ABSENT, Presence.PRESENT))
    assert B3().explain(env, [Query("a", A)])["a"].reason == "ambiguidade"


def test_b3_replay_invalid():
    env = ex07_env(finals={"x0": {}, "x1": {A: Presence.PRESENT, B: Presence.PRESENT}})
    out = B3().explain(env, [Query("a", A)])["a"]
    assert out.state == OutputState.INFORMACAO_INSUFICIENTE and out.reason == "replay_invalido"


def test_b3_budget_and_capabilities():
    assert B3().explain(ex07_env(budget=3), [Query("a", A)])["a"].state == OutputState.ORCAMENTO_ESGOTADO
    rc = B3().explain(ex07_env(capability_="R-C"), [Query("a", A)])["a"]
    assert rc.state == OutputState.INFORMACAO_INSUFICIENTE
    inadm = ex07_env(inadmissible=frozenset({frozenset({"ent_thr"})}))
    assert B3().explain(inadm, [Query("a", A)])["a"].state == OutputState.CONTRAFACTUAL_INDISPONIVEL
