"""A19: `pipeline.core` (lead α, read-only) against the brute-force core of `test_spec_examples.py`.

The reference is written from the SPEC and imports nothing from `habench`. Random responses have duplicate
entity Ids, repeated codes, cs ties, entities without concepts and HYPOTHETICAL scores around the vetoes.
"""

from hypothesis import given, settings
from hypothesis import strategies as st
from test_spec_examples import build_records, norm_variants

from habench.oracle import toy
from habench.pipeline import core
from habench.pipeline.catalog import Config

MED = 900_000_001
HIER = toy.hierarchy()
CODES = ["C61", "E11.9", "E11.65", "E11", "R50.9", "J45.0", "D49.2"]
SCORES = [0.3, 0.55, 0.6, 0.62, 0.65, 0.7, 0.9, 0.95]

trait_st = st.lists(
    st.one_of(
        st.tuples(st.sampled_from(["NEGATION", "DIAGNOSIS", "SIGN", "SYMPTOM", "LOW_CONFIDENCE",
                                   "PERTAINS_TO_FAMILY"]), st.sampled_from([0.3, 0.8, 0.9])),
        st.tuples(st.just("HYPOTHETICAL"), st.sampled_from([0.55, 0.6, 0.62, 0.65, 0.7])),
    ),
    max_size=3,
    unique_by=lambda t: t[0],
)
entity_st = st.fixed_dictionaries({
    "id": st.integers(1, 3),
    "type": st.sampled_from(["DX_NAME", "SYSTEM_ORGAN_SITE"]),
    "score": st.sampled_from(SCORES),
    "traits": trait_st,
    "concepts": st.lists(st.tuples(st.sampled_from(CODES), st.sampled_from(SCORES)), max_size=3),
})
config_st = st.fixed_dictionaries({
    "occ": st.sampled_from(["last_upsert", "first_upsert", "per_entity_any"]),
    "sel": st.sampled_from(["all", "top1"]),
    "ent_thr": st.sampled_from([0.55, 0.6, 0.65, 0.7]),
    "icd_thr": st.sampled_from([0.3, 0.55, 0.6, 0.65]),
    "trait": st.sampled_from(["v1", "v1_hyp_le_0.6", "v1_no_required", "v2", "neg_only"]),
    "map": st.sampled_from(["cm_gated", "cm_ungated", "who_exact_fb", "who_exact", "who_cat3"]),
})


def reference_present(entities: list[dict], cfg: dict, space: str) -> set[str]:
    evidence = {"model_version": toy.MODEL_VERSION, "entities": entities}
    recs = build_records(evidence, cfg, norm_variants(cfg, None), space)
    return {r.key for r in recs if r.key is not None and not r.failed}


@settings(max_examples=600, deadline=None)
@given(st.lists(entity_st, min_size=1, max_size=5), config_st, st.sampled_from(["CM", "WHO"]))
def test_core_matches_brute_force(entities, cfg, space):
    if space == "CM" and not cfg["map"].startswith("cm_"):
        cfg = dict(cfg, map="cm_gated")
    raw = toy.response(
        toy.entity(e["id"], e["score"], e["concepts"], e["traits"], e["type"]) for e in entities
    )
    ev = toy.evidence({MED: raw})
    res = core.run(Config.of(cfg), ev, HIER, core.CM if space == "CM" else core.WHO, trace=True)
    got = {k.code for k in res.present}
    ref_entities = [
        {"id": e["id"], "type": e["type"], "score": e["score"], "traits": [list(t) for t in e["traits"]],
         "concepts": [list(c) for c in e["concepts"]]}
        for e in entities
    ]
    assert got == reference_present(ref_entities, cfg, space)
    # per record: code, key and the set of failed predicates (SPEC 3.2 trace summary)
    failed: dict[int, set[str]] = {}
    for d in res.trace.decisions:
        if not d.verdict:
            failed.setdefault(d.ref, set()).add(STAGE[d.stage])
    core_recs = sorted(
        (r.code, "" if r.key is None or r.rid in failed else r.key.code, tuple(sorted(failed.get(r.rid, ()))))
        for r in res.trace.records
    )
    evidence = {"model_version": toy.MODEL_VERSION, "entities": ref_entities}
    ref_recs = sorted(
        (r.code, "" if r.failed or r.key is None else r.key, tuple(sorted(r.failed)))
        for r in build_records(evidence, cfg, norm_variants(cfg, None), space)
    )  # keys are compared on approved records only
    assert core_recs == ref_recs


STAGE = {"map": "map", "icd_thr": "icd_thr", "ent_thr": "ent_thr", "trait_veto": "trait", "trait_hyp": "trait",
         "trait_required": "trait", "trait_type": "trait"}
