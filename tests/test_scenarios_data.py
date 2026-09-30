"""Toy groups shared by the scenario tests (no tests in this module)."""

from habench.oracle import toy
from habench.pipeline.evidence import Evidence
from habench.pipeline.mapping import Hierarchy

MED = 900_000_001
MED2 = 900_000_002
MED_FAILED = 900_000_003
SEED = 20260930


def toy_entities() -> list[dict]:
    """Seven entities: a repeated Id (1) and repeated codes (C61, R50.9, E11.9), a code outside the V1 gate
    (D49.2), HYPOTHETICAL and NEGATION traits, and es values in [0.55, 0.60)."""
    return [
        toy.entity(1, 0.59, [("C61", 0.90), ("E11.9", 0.50)]),
        toy.entity(2, 0.65, [("E11.9", 0.80), ("E11.65", 0.70)]),
        toy.entity(3, 0.72, [("R50.9", 0.75), ("J45.0", 0.62)], traits=(("SYMPTOM", 0.9),)),
        toy.entity(1, 0.95, [("C61", 0.65), ("R50.9", 0.40)]),
        toy.entity(4, 0.85, [("D49.2", 0.90), ("E11.9", 0.30)]),
        toy.entity(5, 0.90, [("J45.0", 0.88), ("R50.9", 0.61)], traits=(("HYPOTHETICAL", 0.62), ("DIAGNOSIS", 0.9))),
        toy.entity(6, 0.66, [("E11.65", 0.85), ("C61", 0.55)], traits=(("NEGATION", 0.7), ("DIAGNOSIS", 0.9))),
    ]


def toy_group(with_failed: bool = False):
    ents = toy_entities()
    responses = {MED: toy.response(ents), MED2: toy.response(ents[:3])}
    meds = (MED, MED2)
    if with_failed:
        responses[MED_FAILED] = None
        meds = (MED, MED2, MED_FAILED)
    return [("g1", meds)], toy.evidence(responses)


def toy_docs() -> dict[int, dict]:
    _, ev = toy_group()
    return {m: ev.extraction_doc(m) for m in (MED, MED2)}


def wide_group(n: int = 60) -> tuple[list, Evidence, Hierarchy]:
    """n distinct categories, each with one entity: es 0.59 (changed by ent_thr 0.55) or 0.90 (unchanged)."""
    cats = [f"K{i:02d}" for i in range(n)]
    hier = Hierarchy.from_rows(
        [{"cd_cat": c, "id_cat": i + 1, "id_group": 1} for i, c in enumerate(cats)], []
    )
    ents = [toy.entity(i + 1, 0.59 if i % 2 == 0 else 0.90, [(c, 0.90)]) for i, c in enumerate(cats)]
    return [("wide", (MED,))], toy.evidence({MED: toy.response(ents)}), hier
