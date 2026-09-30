"""T13 acceptance: M equals the oracle in 100% of cases under L2-M × R-A with unlimited budget, through the real view
builder and broker, with every certificate true and the SPEC 9.2 coverage satisfied. Plus: every method runs under
the isolation hook without failing, and the spawn cost is measured."""

from __future__ import annotations

import time
from itertools import combinations

import pytest

from habench.env.broker import BrokerEnv
from habench.env.rpc import run_isolated
from habench.methods.base import Query
from habench.methods.m import M
from habench.oracle import toy
from habench.oracle.contrast import make_contrast
from habench.oracle.hybrids import Hybrids, all_subsets
from habench.oracle.truth import CellSpec, build_truth
from habench.pipeline.catalog import V1, V2
from habench.pipeline.evidence import JsonEdit, Patch
from habench.runner.batch import BUGDOC_DIR
from habench.runner.matrix import DEFAULT_METHODS, METHODS
from habench.types import OutputState
from habench.views.build import Texts, build_view

HIER = toy.hierarchy()
KEY = b"k" * 32
M1, M2 = 910_000_001, 910_000_002
E = toy.entity


def _ev(*responses):
    return toy.evidence({m: toy.response(r) for m, r in zip((M1, M2), responses, strict=False)})


def cases():
    """(name, contrast, evidence): SPEC examples on a two-medication toy group."""
    diag_hyp = (("HYPOTHETICAL", 0.62), ("DIAGNOSIS", 0.9))
    base2 = [E(1, 0.9, [("E11.9", 0.8), ("E11.65", 0.7)]), E(2, 0.9, [("R50.9", 0.75), ("J45.0", 0.75)])]
    ex05 = [E(1, 0.9, [("C61", 0.85)], (("NEGATION", 0.8), ("DIAGNOSIS", 0.9))), E(2, 0.7, [("C61", 0.8)]),
            E(3, 0.92, [("E11.9", 0.81)]), E(4, 0.95, [("R50.9", 0.9)]), E(5, 0.58, [("R50.9", 0.9)])]
    p1 = Patch("p1", (JsonEdit(M1, ("Entities", 0, "Score"), 0.62),))
    p3 = Patch("p3", (JsonEdit(M1, ("Entities", 0, "ICD10CMConcepts", 0, "Score"), 0.66),))
    p2 = Patch("p2", (JsonEdit(M1, ("Entities", 0, "Score"), 0.75),))
    out = [
        ("ex07", make_contrast("c07", "g", [M1, M2], "who", V1, V1.with_(ent_thr=0.58, icd_thr=0.55), patches=[p1],
                               check_sealed=False), _ev([E(1, 0.59, [("C61", 0.9)])], base2)),
        ("ex08", make_contrast("c08", "g", [M1, M2], "who", V1, V1.with_(ent_thr=0.70), patches=[p2],
                               check_sealed=False), _ev([E(1, 0.65, [("C61", 0.9)])], base2)),
        ("ex09", make_contrast("c09", "g", [M1, M2], "who", V1, V1.with_(ent_thr=0.55, icd_thr=0.55),
                               check_sealed=False), _ev([E(1, 0.58, [("C61", 0.58)])], base2)),
        ("ex10", make_contrast("c10", "g", [M1, M2], "who", V1, V1.with_(ent_thr=0.55, icd_thr=0.65), patches=[p3],
                               check_sealed=False), _ev([E(1, 0.58, [("C61", 0.62)])], base2)),
        ("ex11", make_contrast("c11", "g", [M1, M2], "who", V1, V1.with_(ent_thr=0.55),
                               d0=V1.with_(trait="v1_hyp_le_0.6"), d1=V1.with_(ent_thr=0.55), check_sealed=False),
         _ev([E(1, 0.58, [("C61", 0.9)], diag_hyp)], base2)),
        ("ex14_components", make_contrast("c14", "g", [M1, M2], "who", V1, V2, check_sealed=False), _ev(ex05, base2)),
        ("ex14_bundle", make_contrast("c14b", "g", [M1, M2], "who", V1, V2, bundles={"V1_TO_V2": V1.diff(V2)},
                                      check_sealed=False), _ev(ex05, base2)),
        ("occ_sel", make_contrast("cos", "g", [M1, M2], "cm", V1.with_(map="cm_ungated"),
                                  V1.with_(map="cm_ungated", occ="per_entity_any", sel="top1"), check_sealed=False),
         _ev(ex05, base2)),
        ("map", make_contrast("cmap", "g", [M1, M2], "who", V1.with_(map="who_exact_fb"),
                              V1.with_(map="who_cat3", ent_thr=0.65), check_sealed=False), _ev(base2, ex05)),
    ]
    return out


def _texts(meds):
    return {m: Texts("pt", "en", "en") for m in meds}


def _queries(hyb: Hybrids):
    keys = set()
    for S in all_subsets(hyb.D):
        if hyb.admissible(S):
            keys |= hyb.run(S).present
    return [(f"q{i}", k) for i, k in enumerate(sorted(keys))]


def _setup(tmp_path, name, c, ev, view="L2-M", capability="R-A", budget=None):
    view_dir, side = build_view(c, view, evidence=ev, hier=HIER, texts=_texts(c.meds), partition="dev", key=KEY,
                                data_dir=tmp_path)
    env = BrokerEnv(side, c, ev, HIER, view_dir, capability, budget)
    return view_dir, side, env


def _coverage(D: frozenset[str], certs, Z: frozenset[str]) -> bool:
    """SPEC 9.2 step 3 with the certified sets `certs` = {T: sufficient?} and the accepted dummies Z."""
    for k in range(len(D) + 1):
        for S in map(frozenset, combinations(sorted(D), k)):
            s = S - Z
            if not any(s == T - Z or (v and s > T - Z) for T, v in certs.items()):
                return False
    return True


@pytest.mark.parametrize("name,c,ev", cases(), ids=[n for n, _, _ in cases()])
def test_m_equals_oracle_l2m_ra_unlimited(tmp_path, name, c, ev):
    hyb = Hybrids(c, ev, HIER)
    qs = _queries(hyb)
    truth = build_truth(hyb, qs, partition="dev", scenario_family="toy", cells=[CellSpec.of("L2-M", "R-A")])
    _, side, env = _setup(tmp_path, name, c, ev)
    out = M().explain(env, [Query(q, k) for q, k in qs])
    member = dict(side.handles) | {h: h for h in env.factors() if not h.startswith("ev:")}
    D = frozenset(hyb.D)
    logged = {frozenset(member[h] for h in s) & D for s in env.ledger.log}
    checked = 0
    for qt in truth.queries:
        e = out[qt.qid]
        if not qt.eligible:
            continue
        if not qt.changed:
            assert e.state == OutputState.AUSENCIA_DE_MUDANCA, (qt.qid, e)
            continue
        assert qt.complete
        assert e.state == OutputState.EXPLICACAO_VERIFICADA, (qt.qid, e)
        fam = frozenset(frozenset(member[h] for h in s) for s in e.families[0])
        assert fam == qt.family, (qt.qid, fam, qt.family)
        certs, Z = {}, set()
        for cert in e.certificates:
            S = frozenset(member.get(h, h) for h in cert.subject) & D
            if cert.kind == "dummy":
                (f,) = cert.subject
                f = member.get(f, f)
                assert f not in D or qt.is_dummy(f), (qt.qid, cert)
                Z.add(f)
            else:
                assert qt.sufficient(S) == cert.value, (qt.qid, cert)
                if cert.kind == "eval":
                    assert S in logged, (qt.qid, cert)  # SPEC 9.2 step 0: eval only from the log
                certs[S] = cert.value
        assert _coverage(D, certs, frozenset(Z)), qt.qid
        checked += 1
    assert checked or all(not q.changed for q in truth.queries)


def test_every_method_runs_isolated_and_spawn_cost(tmp_path):
    name, c, ev = cases()[0]
    view_dir, side, _ = _setup(tmp_path, name, c, ev)
    qs = [Query(q, k) for q, k in _queries(Hybrids(c, ev, HIER))]
    timings = {}
    for m in (*DEFAULT_METHODS, "m_lenient"):
        env = BrokerEnv(side, c, ev, HIER, view_dir, "R-A", 64)
        t0 = time.monotonic()
        res = run_isolated(METHODS[m], env, qs, view_dir=view_dir, truth_root=tmp_path / "truth",
                           extra_read=[BUGDOC_DIR], timeout=120)
        timings[m] = time.monotonic() - t0
        assert res.error is None, (m, res.error)
        failed = [e for e in res.explanations.values() if e.state == OutputState.FALHA_DE_EXECUCAO]
        assert not failed, (m, failed)
    print("run_isolated wall seconds:", {k: round(v, 3) for k, v in timings.items()})
