"""Toy hierarchy and responses of the SPEC examples, for unit tests (never used on real data)."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence

from habench.pipeline.evidence import Evidence
from habench.pipeline.mapping import Hierarchy

MODEL_VERSION = "3.0.0.20231001"
CATS = ("C61", "E11", "J45", "R50")
SUBCATS = ("E119", "J450", "R509")


def hierarchy() -> Hierarchy:
    """cat = {C61, E11, J45, R50}, subcat = {E119, J450, R509} (SPEC EX-01)."""
    cats = [{"cd_cat": c, "id_cat": i + 1, "id_group": 1} for i, c in enumerate(CATS)]
    cat_id = {c: i + 1 for i, c in enumerate(CATS)}
    subs = [{"cd_subcat": s, "id_subcat": i + 1, "id_cat": cat_id[s[:3]]} for i, s in enumerate(SUBCATS)]
    return Hierarchy.from_rows(cats, subs)


def entity(
    eid: int,
    score: float,
    concepts: Sequence[tuple[str, float]],
    traits: Sequence[tuple[str, float]] = (("DIAGNOSIS", 0.9),),
    type_: str = "DX_NAME",
) -> dict:
    return {
        "Id": eid,
        "Type": type_,
        "Score": score,
        "Traits": [{"Name": n, "Score": s} for n, s in traits],
        "ICD10CMConcepts": [{"Code": c, "Score": s} for c, s in concepts],
    }


def response(entities: Iterable[dict]) -> str:
    return json.dumps({"Entities": list(entities), "ModelVersion": MODEL_VERSION})


def evidence(responses: Mapping[int, str | None]) -> Evidence:
    """Evidence of `responses` (med -> raw response; None = failed row)."""
    return Evidence.from_responses(list(responses.items()))
