"""BrokerEnv on toy contrasts (SPEC 5.4, 7.1-7.4, 11.1)."""

from __future__ import annotations

import re
from itertools import combinations
from pathlib import Path

import pytest

from habench.env.broker import BrokerEnv, expressible
from habench.methods.b3 import B3
from habench.methods.base import (
    INADMISSIBLE,
    NO_REPLAY,
    NOT_EXPRESSIBLE,
    NOT_VISIBLE,
    ArtifactRef,
    BudgetExhausted,
    PresenceMap,
    Query,
    Unavailable,
)
from habench.oracle import toy
from habench.oracle.contrast import make_contrast
from habench.oracle.hybrids import Hybrids
from habench.pipeline.catalog import V1, V2
from habench.pipeline.evidence import JsonEdit, Patch
from habench.types import SYSTEM_ICD10_WHO, AssocKey, OutputState, Presence
from habench.views.layout import BrokerSide, Entry, Manifest, patch_handle

MED = 900_000_001
HIER = toy.hierarchy()
KEY = AssocKey(MED, SYSTEM_ICD10_WHO, HIER.version, "C61")
HMAC_KEY = b"k" * 32


def ev(es=0.59, cs=0.9, traits=(("DIAGNOSIS", 0.9),), concepts=None):
    concepts = concepts or [("C61", cs)]
    return toy.evidence({MED: toy.response([toy.entity(1, es, concepts, traits)])})


def make_view(tmp_path: Path, vid: str = "v1") -> tuple[Path, dict[str, bytes]]:
    blobs = {"a1": b"hello", "a2": b"0123456789"}
    d = tmp_path / "view"
    d.mkdir(exist_ok=True)
    entries = []
    for ref, data in blobs.items():
        (d / f"{ref}.bin").write_bytes(data)
        entries.append(Entry(ref, "acm_response" if ref == "a1" else "trace", "x0" if ref == "a1" else "x1", "00"))
    (d / "manifest.json").write_text(Manifest(vid, tuple(entries)).to_json(), encoding="utf-8")
    return d, blobs


def make_env(tmp_path, contrast, evidence, view="L2-R", capability="R-A", budget=None, **kw) -> BrokerEnv:
    d, _ = make_view(tmp_path)
    handles = tuple((patch_handle(HMAC_KEY, contrast.cid, p.factor), p.factor) for p in contrast.patches)
    side = BrokerSide("v1", "dev", contrast.cid, view, handles)
    return BrokerEnv(side, contrast, evidence, HIER, d, capability, budget, **kw)


def subsets(names):
    names = sorted(names)
    return [frozenset(c) for k in range(len(names) + 1) for c in combinations(names, k)]


def ex07():
    p1 = Patch("p1", (JsonEdit(MED, ("Entities", 0, "Score"), 0.62),))
    return make_contrast("c", "g", [MED], "who", V1, V1.with_(ent_thr=0.58, icd_thr=0.55), patches=[p1],
                         check_sealed=False)


def ex11():
    """Declared d0 trait = v1_hyp_le_0.6 (documentation), executed x0 trait = v1 (code)."""
    x1 = V1.with_(ent_thr=0.55)
    c = make_contrast("c", "g", [MED], "who", V1, x1, d0=V1.with_(trait="v1_hyp_le_0.6"), d1=x1, check_sealed=False)
    return c, ev(es=0.58, traits=(("HYPOTHETICAL", 0.62), ("DIAGNOSIS", 0.9)))


def test_ex07_equals_hybrids_truth_for_every_s(tmp_path):
    c = ex07()
    env = make_env(tmp_path, c, ev())
    truth = Hybrids(c, ev(), HIER)
    handles = env.factors()
    assert len(handles) == 3 and not any("patch:" in h for h in handles)
    (opaque,) = [h for h in handles if h.startswith("ev:")]
    assert re.fullmatch(r"ev:[0-9a-f]{8}", opaque) and opaque == patch_handle(HMAC_KEY, "c", "patch:p1")
    assert list(handles) == sorted(handles)
    to_member = {opaque: "patch:p1"}
    for S in subsets(handles):
        got = env.evaluate(S).presence
        want = truth.run({to_member.get(h, h) for h in S})
        assert got == PresenceMap(want.present, ()), S
        assert env.evaluate(S).state(KEY) == want.state(KEY)
    assert env.meter().evaluations == 8
    assert env.final("x0") == PresenceMap() and env.final("x1") == PresenceMap([KEY])
    assert env.meter().evaluations == 8  # finals are free


def test_trace_records(tmp_path):
    env = make_env(tmp_path, ex07(), ev())
    (rec,) = env.evaluate(frozenset()).trace
    assert (rec.med, rec.code, rec.key) == (MED, "C61", KEY)
    assert rec.verdict is False and rec.failed == {"ent_thr"}
    (rec,) = env.evaluate(frozenset({"ent_thr"})).trace
    assert rec.verdict is True and rec.failed == frozenset()


def test_trait_stages_collapse_to_trait(tmp_path):
    c = make_contrast("c", "g", [MED], "who", V1, V1.with_(ent_thr=0.55), check_sealed=False)
    env = make_env(tmp_path, c, ev(es=0.9, traits=(("NEGATION", 0.9), ("DIAGNOSIS", 0.9))))
    (rec,) = env.evaluate(frozenset()).trace
    assert rec.failed == {"trait"} and not rec.verdict


def test_unavailable_meds_are_marked(tmp_path):
    c = make_contrast("c", "g", [MED], "who", V1, V1.with_(ent_thr=0.55), check_sealed=False)
    env = make_env(tmp_path, c, toy.evidence({MED: None}))
    r = env.evaluate(frozenset())
    assert r.presence == PresenceMap((), [MED]) and r.state(KEY) == Presence.UNAVAILABLE
    assert env.final("x0").get(KEY) == Presence.UNAVAILABLE


def test_ex11_with_code_link_replays_executed_and_trait_is_inert(tmp_path):
    c, e = ex11()
    env = make_env(tmp_path, c, e)
    assert env.factors() == ("ent_thr", "trait")
    assert env.evaluate(frozenset({"ent_thr"})).state(KEY) == Presence.PRESENT  # the executed truth
    assert env.evaluate(frozenset({"ent_thr", "trait"})) == env.evaluate(frozenset({"ent_thr"}))
    assert env.meter().evaluations == 1
    b = make_env(tmp_path, c, e)
    assert b.evaluate(frozenset({"trait"})) == b.evaluate(frozenset())
    assert b.meter().evaluations == 1
    assert env.executed_config("x0")["trait"] == "v1" and env.config("x0")["trait"] == "v1_hyp_le_0.6"


def test_ex11_without_code_link_uses_declared_levels(tmp_path):
    c, e = ex11()
    env = make_env(tmp_path, c, e, view="L2-R-A3")
    assert env.factors() == ("ent_thr", "trait")
    state = {S: env.evaluate(S).state(KEY) for S in subsets(env.factors())}
    # endpoints validate, the middle differs from the truth ({ent_thr} is present in the executed truth)
    assert env.evaluate(frozenset()).presence == env.final("x0")
    assert env.evaluate(frozenset(env.factors())).presence == env.final("x1")
    assert [S for S, st in state.items() if st == Presence.PRESENT] == [frozenset({"ent_thr", "trait"})]
    with pytest.raises(Unavailable) as e_:
        env.executed_config("x0")
    assert e_.value.reason == NOT_VISIBLE
    # SPEC EX-11, L2-R-A3 x R-A: W = {{ent_thr}}, {{ent_thr, trait}}; the method concludes {{ent_thr, trait}}
    out = B3().explain(make_env(tmp_path, c, e, view="L2-R-A3"), [Query("q", KEY)])["q"]
    assert out.state == OutputState.EXPLICACAO_VERIFICADA and out.families == ((("ent_thr", "trait"),),)


def test_l1_needs_rc(tmp_path):
    c = ex07()
    for cap in ("R-A", "R-B"):
        with pytest.raises(ValueError):
            make_env(tmp_path, c, ev(), view="L1", capability=cap)
    env = make_env(tmp_path, c, ev(), view="L1", capability="R-C")
    assert env.factors() == ("ent_thr", "icd_thr")  # no patch handle: responses are not visible
    with pytest.raises(Unavailable) as e:
        env.evaluate(frozenset())
    assert e.value.reason == NO_REPLAY
    assert env.final("x1") == PresenceMap([KEY])


def test_rc_refuses_everything_but_unknown_handle_is_value_error(tmp_path):
    env = make_env(tmp_path, ex07(), ev(), capability="R-C")
    for S in subsets(env.factors()):
        with pytest.raises(Unavailable) as e:
            env.evaluate(S)
        assert e.value.reason == NO_REPLAY
    with pytest.raises(ValueError):
        env.evaluate(frozenset({"nope"}))
    with pytest.raises(ValueError):
        env.evaluate(frozenset({"patch:p1"}))  # the member name is not a handle
    assert env.meter().evaluations == 0


def test_budget_and_cache(tmp_path):
    env = make_env(tmp_path, ex07(), ev(), budget=2)
    env.evaluate(frozenset())
    env.evaluate(frozenset({"ent_thr"}))
    with pytest.raises(BudgetExhausted):
        env.evaluate(frozenset({"icd_thr"}))
    env.evaluate(frozenset({"ent_thr"}))
    assert env.meter().evaluations == 2
    assert env.contrast().budget == 2


def test_prep_admissibility_and_rb(tmp_path):
    x1 = V1.with_(ent_thr=0.55)
    c = make_contrast("c", "g", [MED], "who", V1, x1, prep=["dup_ind", "mask_drug"],
                      prep_available=[["dup_ind", "mask_drug"]], check_sealed=False)
    both = frozenset({"dup_ind", "mask_drug"})
    env = make_env(tmp_path, c, ev(es=0.58), prep_evidence={("dup_ind", "mask_drug"): ev(es=0.62)})
    with pytest.raises(Unavailable) as e:
        env.evaluate(frozenset({"dup_ind"}))
    assert e.value.reason == INADMISSIBLE
    assert env.evaluate(both).state(KEY) == Presence.PRESENT
    assert env.meter().evaluations == 1
    rb = make_env(tmp_path, c, ev(es=0.58), capability="R-B", prep_evidence={("dup_ind", "mask_drug"): ev(0.62)})
    with pytest.raises(Unavailable) as e:
        rb.evaluate(both)
    assert e.value.reason == NO_REPLAY
    assert rb.evaluate(frozenset({"ent_thr"})).state(KEY) == Presence.PRESENT  # es 0.58 >= 0.55, on x0's stored response
    assert rb.meter().evaluations == 1


def test_n2_not_expressible_costs_nothing(tmp_path):
    x1 = V1.with_(ent_thr=0.55, trait="v1_no_required")
    c = make_contrast("c", "g", [MED], "who", V1, x1, check_sealed=False)
    env = make_env(tmp_path, c, ev(es=0.58), view="N2")
    assert env.factors() == ("ent_thr", "trait")
    assert env.evaluate(frozenset({"ent_thr"})).state(KEY) == Presence.PRESENT
    for S in (frozenset({"trait"}), frozenset({"ent_thr", "trait"})):
        with pytest.raises(Unavailable) as e:
            env.evaluate(S)
        assert e.value.reason == NOT_EXPRESSIBLE
    assert env.meter().evaluations == 1
    with pytest.raises(Unavailable) as e:
        env.executed_config("x0")  # N views have no code link
    assert e.value.reason == NOT_VISIBLE


def test_expressible():
    def h(c):
        return Hybrids(c, ev(es=0.58), HIER, levels="declared")

    x1 = V1.with_(ent_thr=0.55, trait="v1_no_required", map="cm_ungated")
    c = make_contrast("c", "g", [MED], "who", V1, x1, check_sealed=False)
    assert expressible("L2-R", h(c), {"trait", "map", "ent_thr"})
    assert expressible("N1", h(c), {"trait", "map", "ent_thr"})
    assert not expressible("N2", h(c), {"map"}) and expressible("N2", h(c), {"ent_thr"})
    v2 = make_contrast("c2", "g", [MED], "who", V1, V1.with_(trait="v2", map="who_exact_fb"), check_sealed=False)
    assert not expressible("N1", h(v2), {"trait"}) and not expressible("N1", h(v2), {"map"})
    bundle = make_contrast("c3", "g", [MED], "who", V1, V2, bundles={"V1_TO_V2": V1.diff(V2)}, check_sealed=False)
    assert not expressible("N1", h(bundle), {"V1_TO_V2"}) and expressible("L3-M", h(bundle), {"V1_TO_V2"})
    # patches are evidence edits: expressible (β's oracle.truth.default_expressible, shared with the truth)
    assert expressible("N1", h(ex07()), {"patch:p1"})
    assert expressible("N1", h(ex07()), {"ent_thr", "icd_thr"})


def test_a2_replays_over_top1_evidence(tmp_path):
    # C61 is the second concept of the entity: it disappears from the top-1 evidence
    concepts = [("E11", 0.95), ("C61", 0.9)]
    e = ev(es=0.58, concepts=concepts)
    c = make_contrast("c", "g", [MED], "who", V1, V1.with_(ent_thr=0.55), check_sealed=False)
    full = make_env(tmp_path, c, e)
    top1 = make_env(tmp_path, c, e, view="L2-R-A2")
    assert full.evaluate(frozenset({"ent_thr"})).state(KEY) == Presence.PRESENT
    assert top1.evaluate(frozenset({"ent_thr"})).state(KEY) == Presence.ABSENT
    assert top1.final("x1").get(KEY) == Presence.PRESENT  # finals stay the executed truth on full evidence
    assert top1.evaluate(frozenset({"ent_thr"})).presence != top1.final("x1")  # the replay does not validate


def test_a2_drops_edits_on_removed_concepts(tmp_path):
    concepts = [("C61", 0.9), ("E11", 0.8)]
    p = Patch("p1", (JsonEdit(MED, ("Entities", 0, "Score"), 0.62),
                     JsonEdit(MED, ("Entities", 0, "ICD10CMConcepts", 1, "Score"), 0.7)))
    c = make_contrast("c", "g", [MED], "who", V1, V1.with_(icd_thr=0.55), patches=[p], check_sealed=False)
    env = make_env(tmp_path, c, ev(es=0.58, concepts=concepts), view="L2-R-A2")
    assert env.dropped_edits == (("p1", 1),)
    (h,) = [h for h in env.factors() if h.startswith("ev:")]
    assert env.evaluate(frozenset({h})).state(KEY) == Presence.PRESENT  # the kept entity-score edit applies


def test_read_artifacts_config_and_meter(tmp_path):
    env = make_env(tmp_path, ex07(), ev())
    assert [(a.ref, a.kind, a.run) for a in env.artifacts()] == [("a1", "acm_response", "x0"), ("a2", "trace", "x1")]
    assert env.read(ArtifactRef("a1", "acm_response", "x0")) == b"hello"
    assert env.read(ArtifactRef("a2", "trace", "x1")) == b"0123456789"
    with pytest.raises(Unavailable) as e:
        env.read(ArtifactRef("../../etc/passwd", "x", ""))
    assert e.value.reason == NOT_VISIBLE
    assert env.meter().bytes_read == 15
    assert env.config("x0") == {"occ": "last_upsert", "sel": "all", "ent_thr": "0.6", "icd_thr": "0.6",
                                "trait": "v1", "map": "cm_gated"}
    assert "patch:p1" not in env.executed_config("x1") and env.executed_config("x1")["ent_thr"] == "0.58"
    info = env.contrast()
    assert (info.cid, info.runs, info.space, info.budget) == ("v1", ("x0", "x1"), "ICD-10-WHO", None)
    assert env.capability() == "R-A"
    env.evaluate(frozenset({"ent_thr"}))
    m = env.meter()
    assert m.evaluations == 1 and m.cpu_seconds >= 0 and m.peak_rss == 0
    with pytest.raises(ValueError):
        env.config("x2")
