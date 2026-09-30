from habench.env.broker import BrokerEnv
from habench.methods.b2 import B2
from habench.methods.base import Query
from habench.oracle import toy
from habench.oracle.contrast import make_contrast
from habench.pipeline.catalog import V1
from habench.pipeline.evidence import JsonEdit, Patch
from habench.types import SYSTEM_ICD10_WHO, AssocKey, OutputState
from habench.views.build import Texts, build_view

HIER = toy.hierarchy()
MED = 920_000_001
C61 = AssocKey(MED, SYSTEM_ICD10_WHO, HIER.version, "C61")


def _env(tmp_path, c, ev, view):
    d, side = build_view(c, view, evidence=ev, hier=HIER, texts={MED: Texts("pt", "en", "en")}, partition="dev",
                         key=b"k" * 32, data_dir=tmp_path)
    return BrokerEnv(side, c, ev, HIER, d, "R-C", None)


def _ev(es, cs):
    return toy.evidence({MED: toy.response([toy.entity(1, es, [("C61", cs)])])})


def test_first_divergent_stage_in_trace(tmp_path):
    c = make_contrast("c", "g", [MED], "who", V1, V1.with_(ent_thr=0.55, icd_thr=0.55), check_sealed=False)
    env = _env(tmp_path, c, _ev(0.58, 0.58), "L2-M")
    out = B2().explain(env, [Query("a", C61)])["a"]
    # icd_thr comes before ent_thr in the core's stage order; B2 reports it without causal claim
    assert out.state == OutputState.EXPLICACAO_VERIFICADA and out.families == ((("icd_thr",),),)
    assert out.notes == ("noncausal",) and out.certificates == ()


def test_response_divergence_points_at_the_patch(tmp_path):
    p = Patch("p1", (JsonEdit(MED, ("Entities", 0, "Score"), 0.62),))
    c = make_contrast("c", "g", [MED], "who", V1, V1.with_(ent_thr=0.58), patches=[p], check_sealed=False)
    env = _env(tmp_path, c, _ev(0.57, 0.9), "L2-M")
    out = B2().explain(env, [Query("a", C61)])["a"]
    (fam,) = out.families
    assert fam[0][0].startswith("ev:")


def test_without_trace_degenerates_to_b1(tmp_path):
    c = make_contrast("c", "g", [MED], "who", V1, V1.with_(ent_thr=0.55, icd_thr=0.55), check_sealed=False)
    env = _env(tmp_path, c, _ev(0.58, 0.58), "L2-R")
    out = B2().explain(env, [Query("a", C61)])["a"]
    assert out.state == OutputState.ALTERNATIVAS and out.families == ((("ent_thr",),), (("icd_thr",),))
