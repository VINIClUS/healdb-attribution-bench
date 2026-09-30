import json

from habench.env.table import TableEnv
from habench.methods.base import ArtifactRef, EvalResult, PresenceMap, Query
from habench.methods.m import M, hypotheses, inventory
from habench.types import SYSTEM_ICD10_WHO, AssocKey, OutputState, Presence

A = AssocKey(1, SYSTEM_ICD10_WHO, "hier:toy", "C61")
V, ALT, INS = OutputState.EXPLICACAO_VERIFICADA, OutputState.ALTERNATIVAS, OutputState.INFORMACAO_INSUFICIENTE


def replay_of(rule):
    def run(s: frozenset[str]) -> EvalResult:
        return EvalResult(PresenceMap([A] if rule(s) else []), ())

    return run


def response(es: float, cs: float, traits=(("DIAGNOSIS", 0.9),), code="C61") -> str:
    ent = {"Id": 1, "Type": "DX_NAME", "Score": es, "Traits": [{"Name": n, "Score": s} for n, s in traits],
           "ICD10CMConcepts": [{"Code": code, "Score": cs}]}
    return json.dumps({"Entities": [ent], "ModelVersion": "3.0.0.20231001"})


def blobs(x0: str, x1: str) -> dict:
    return {ArtifactRef("r0", "acm_response", "x0"): json.dumps({"1": x0}).encode(),
            ArtifactRef("r1", "acm_response", "x1"): json.dumps({"1": x1}).encode()}


def assert_certificates_true(expl, suff, D):
    for c in expl.certificates:
        if c.kind in ("final", "eval"):
            assert suff(frozenset(c.subject) & frozenset(D)) == c.value, c


def test_ex07_with_code_link():
    D = ("ent_thr", "ev:p1", "icd_thr")
    rule = lambda s: bool({"ent_thr", "ev:p1"} & s)  # noqa: E731
    cfg = {"x0": {"ent_thr": "0.6", "icd_thr": "0.6"}, "x1": {"ent_thr": "0.58", "icd_thr": "0.55"}}
    env = TableEnv(D, replay_of(rule), configs=cfg, executed=cfg)
    out = M().explain(env, [Query("a", A)])["a"]
    assert out.state == V and out.families == ((("ent_thr",), ("ev:p1",)),)
    assert_certificates_true(out, rule, D)
    assert env.meter().evaluations == 5  # ∅, D and the 3 singletons; every pair contains a found set


def test_ex11_without_code_link_gives_alternatives():
    # declared d0 trait = v1_hyp_le_0.6 (documentation), executed x0 = v1 (code); replay uses declared levels
    D = ("ent_thr", "trait")
    cfg = {"x0": {"ent_thr": "0.6", "trait": "v1_hyp_le_0.6"}, "x1": {"ent_thr": "0.55", "trait": "v1"}}
    env = TableEnv(D, replay_of(lambda s: s == frozenset(D)), configs=cfg)
    assert len(hypotheses(inventory(env), D)) == 3
    out = M().explain(env, [Query("a", A)])["a"]
    assert out.state == ALT
    assert set(out.families) == {(("ent_thr",),), (("ent_thr", "trait"),)}


def test_ex11_with_code_link_is_identified():
    D = ("ent_thr", "trait")
    cfg = {"x0": {"ent_thr": "0.6", "trait": "v1_hyp_le_0.6"}, "x1": {"ent_thr": "0.55", "trait": "v1"}}
    ex = {"x0": {"ent_thr": "0.6", "trait": "v1"}, "x1": {"ent_thr": "0.55", "trait": "v1"}}
    env = TableEnv(D, replay_of(lambda s: "ent_thr" in s), configs=cfg, executed=ex, inert=frozenset({"trait"}))
    out = M().explain(env, [Query("a", A)])["a"]
    assert out.state == V and out.families == ((("ent_thr",),),)
    assert any(n.startswith("declared_config:refutado") for n in out.notes)


def test_ex11_trace_refutes_declared_history():
    """L2-M without the code link (A3): the stored x0 trace rules the declared history out."""
    D = ("ent_thr", "trait")
    cfg = {"x0": {"ent_thr": "0.6", "trait": "v1_hyp_le_0.6"}, "x1": {"ent_thr": "0.55", "trait": "v1"}}

    def failed(s):
        return frozenset(({"ent_thr"} if "ent_thr" not in s else set()) | ({"trait"} if "trait" not in s else set()))

    def run(s):
        from habench.methods.base import TraceRecord

        f = failed(s)
        return EvalResult(PresenceMap([A] if not f else []), (TraceRecord(1, "C61", A, not f, f),))

    def stored(f):
        decisions = [{"ref": 0, "stage": st, "verdict": st not in f} for st in ("map", "trait_hyp", "ent_thr", "icd_thr")]
        return json.dumps({"candidates": [], "records": [{"rid": 0, "med": 1, "code": "C61",
                                                          "key": [1, A.system, A.version, "C61"]}],
                           "decisions": decisions}).encode()

    blobs_ = {ArtifactRef("t0", "trace", "x0"): stored({"ent_thr"}), ArtifactRef("t1", "trace", "x1"): stored(set())}
    env = TableEnv(D, run, configs=cfg, blobs=blobs_)
    out = M().explain(env, [Query("a", A)])["a"]
    assert out.state == V and out.families == ((("ent_thr",),),)
    # the eval certificates are phrased on the replay's handles (trait always switched): true once intersected
    assert ("eval", ("ent_thr", "trait"), True) in {(c.kind, c.subject, c.value) for c in out.certificates}


def test_ex12_no_replay_uses_dummy():
    D = ("ent_thr", "icd_thr")
    cfg = {"x0": {"ent_thr": "0.6", "icd_thr": "0.6"}, "x1": {"ent_thr": "0.55", "icd_thr": "0.55"}}
    rule = lambda s: "ent_thr" in s  # noqa: E731
    env = TableEnv(D, replay_of(rule), capability_="R-C", configs=cfg, executed=cfg,
                   blobs=blobs(response(0.58, 0.90), response(0.58, 0.90)))
    out = M().explain(env, [Query("a", A)])["a"]
    assert out.state == V and out.families == ((("ent_thr",),),)
    assert ("dummy", ("icd_thr",), True) in {(c.kind, c.subject, c.value) for c in out.certificates}
    assert env.meter().evaluations == 0


def test_no_replay_hidden_trait_band_is_ambiguous_when_strict():
    D = ("ent_thr",)
    cfg = {"x0": {"ent_thr": "0.6", "trait": "v1"}, "x1": {"ent_thr": "0.55", "trait": "v1"}}
    hyp = (("HYPOTHETICAL", 0.62), ("DIAGNOSIS", 0.9))
    env = TableEnv(D, replay_of(lambda s: "ent_thr" in s), capability_="R-C", configs=cfg, executed=cfg,
                   blobs=blobs(response(0.58, 0.9, hyp), response(0.58, 0.9, hyp)))
    strict = M().explain(env, [Query("a", A)])["a"]
    assert strict.state == INS and strict.reason == "ambiguidade"
    assert M(rigor="lenient").explain(env, [Query("a", A)])["a"].state == V


def test_l1_strict_abstains_lenient_explains():
    D = ("ent_thr",)
    cfg = {"x0": {"ent_thr": "0.6", "trait": "v1"}, "x1": {"ent_thr": "0.55", "trait": "v1"}}
    env = TableEnv(D, replay_of(lambda s: "ent_thr" in s), capability_="R-C", configs=cfg)
    assert M().explain(env, [Query("a", A)])["a"].reason == "evidencia_oculta"
    assert M(rigor="lenient").explain(env, [Query("a", A)])["a"].families == ((("ent_thr",),),)


def test_budget_and_unchanged():
    D = ("a1", "a2", "a3")
    env = TableEnv(D, replay_of(lambda s: {"a1", "a2"} <= s), budget=3)
    other = AssocKey(2, SYSTEM_ICD10_WHO, "hier:toy", "E11")
    out = M().explain(env, [Query("a", A), Query("b", other)])
    assert out["a"].state == OutputState.ORCAMENTO_ESGOTADO
    assert out["b"].state == OutputState.AUSENCIA_DE_MUDANCA


def test_replay_invalid():
    D = ("ent_thr",)
    env = TableEnv(D, replay_of(lambda s: "ent_thr" in s),
                   finals={"x0": PresenceMap([A]), "x1": PresenceMap([A], [])})
    env2 = TableEnv(D, replay_of(lambda s: False), finals={"x0": PresenceMap(), "x1": PresenceMap([A])})
    assert M().explain(env, [Query("a", A)])["a"].state == OutputState.AUSENCIA_DE_MUDANCA
    assert M().explain(env2, [Query("a", A)])["a"].reason == "replay_invalido"


def test_inadmissible_gives_contrafactual():
    D = ("p1", "p2", "ent_thr")
    env = TableEnv(D, replay_of(lambda s: {"p1", "p2"} <= s or "ent_thr" in s),
                   inadmissible=frozenset({frozenset({"p1"}), frozenset({"p2"})}))
    out = M().explain(env, [Query("a", A)])["a"]
    assert out.state == OutputState.CONTRAFACTUAL_INDISPONIVEL
