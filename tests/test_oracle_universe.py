import pytest

from habench.oracle import toy
from habench.oracle.contrast import make_contrast
from habench.oracle.hybrids import Hybrids
from habench.oracle.reference import UniverseCache, ident_fn, identify_query
from habench.oracle.truth import CellSpec, build_truth
from habench.oracle.universe import BatchEval, alphabet, hypotheses, symbolize
from habench.pipeline.catalog import V1, V2
from habench.types import SYSTEM_ICD10_WHO, AssocKey

MED = 900_000_001
HIER = toy.hierarchy()
F = lambda *s: frozenset(frozenset(x) for x in s)  # noqa: E731


def test_hypothesis_count_and_true_levels():
    hs = hypotheses(V1, V2, code_link=False, max_dev=3)
    assert len(hs) == len({(h.x0, h.x1, h.variants0, h.variants1) for h in hs})
    assert hs[0].deviations == () and hs[0].x0 == V1 and hs[0].x1 == V2
    linked = hypotheses(V1, V2, code_link=True, max_dev=3, true=(V1, V2, frozenset(), frozenset()))
    assert all(h.x0 == V1 and h.x1 == V2 for h in linked)  # with the code link only variants deviate
    assert len(linked) < len(hs)


def test_batch_eval_matches_hybrids_for_a_symbolized_bundle():
    hs = hypotheses(V1, V1.with_(ent_thr=0.55, icd_thr=0.55), code_link=False, max_dev=0)
    alpha = alphabet(hs, HIER, "who", "C61")
    doc = {"Entities": [toy.entity(1, 0.58, [("C61", 0.9)])], "ModelVersion": toy.MODEL_VERSION}
    b = symbolize(doc, HIER, "who", "C61", alpha)
    assert b is not None
    (D, tab), = BatchEval(HIER, "who", "C61").tables([b], hs[0])
    c = make_contrast("c", "g", [MED], "who", V1, V1.with_(ent_thr=0.55, icd_thr=0.55))
    h = Hybrids(c, toy.evidence({MED: toy.response(doc["Entities"])}), HIER)
    key = AssocKey(MED, SYSTEM_ICD10_WHO, HIER.version, "C61")
    from habench.oracle.hybrids import all_subsets

    assert [h.state(S, key).value for S in all_subsets(D)] == list(tab)


@pytest.fixture(scope="module")
def ex12():
    x1 = V1.with_(ent_thr=0.55, icd_thr=0.55)
    c = make_contrast("c12", "g", [MED], "who", V1, x1)
    ev = toy.evidence({MED: toy.response([toy.entity(1, 0.58, [("C61", 0.9)]), toy.entity(2, 0.9, [("R50.9", 0.9)])])})
    return c, ev


def test_l1_expansion_on_ex12(ex12):
    c, ev = ex12
    key = AssocKey(MED, SYSTEM_ICD10_WHO, HIER.version, "C61")
    cache = UniverseCache(L=2, max_dev=1, time_budget=60)
    cells = [CellSpec.of("L1", "R-C"), CellSpec.of("L2-R", "R-C"), CellSpec.of("L2-M", "R-C")]
    t = build_truth(Hybrids(c, ev, HIER), [("q", key)], partition="dev", scenario_family="F", cells=cells,
                    ident=ident_fn(c, ev, HIER, cache))
    q = t.query("q")
    l1 = q.ident[("L1", "R-C")]
    assert {F(["ent_thr"]), F(["icd_thr"]), F(["ent_thr", "icd_thr"])} <= l1.W_hi
    assert l1.W_lo >= {F(["ent_thr"]), F(["icd_thr"])}
    assert q.cell("L1", "R-C") == "ambiguo"
    # with the full response the evidence is observed: EX-12's L2-R x R-C is identified (U over hypotheses only)
    assert q.cell("L2-R", "R-C") in ("identificado", "ambiguo")
    assert cache.stats and cache.stats[0]["hypotheses"] > 1


def test_unsupported_cells_stay_out(ex12):
    c, ev = ex12
    key = AssocKey(MED, SYSTEM_ICD10_WHO, HIER.version, "C61")
    cells = [CellSpec.of("L2-R-A2", "R-C"), CellSpec.of("L2-M-A2", "R-C")]
    t = build_truth(Hybrids(c, ev, HIER), [("q", key)], partition="dev", scenario_family="I",
                    cells=cells, ident=ident_fn(c, ev, HIER, UniverseCache(L=2, max_dev=0)))
    assert t.query("q").cell("L2-R-A2", "R-C") in ("identificado", "ambiguo", "indeterminado")
    with pytest.raises(KeyError):
        t.query("q").cell("L2-M-A2", "R-C")  # trace over expanded bundles is not covered
    with pytest.raises(NotImplementedError):
        identify_query(c, ev, HIER, t.query("q"), CellSpec.of("L2-M-A2", "R-C"), cache=UniverseCache())
