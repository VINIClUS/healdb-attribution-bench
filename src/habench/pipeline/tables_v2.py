"""V2 intermediate and final tables rebuilt from V2 ACM responses.

Sources (V2 HEAD): process_disease_data_json.py (entity_icd, entity_trait) and
link_medications_with_diseases.py (cutoff_audit, medication_disease). Rows are plain dicts with the
dump column names and MySQL value types (booleans as 0/1 ints, JSON as text, doubles as floats);
`dt_created` is not modelled. Compare with `tables_v1.compare_rows`.
"""

from __future__ import annotations

import json
from collections.abc import Iterable

from habench.pipeline import mapping
from habench.pipeline.evidence import collation_key
from habench.pipeline.mapping import Hierarchy

ICD_HIGH_MIN = 0.60
ICD_MEDIUM_MIN = 0.30
ENTITY_SCORE_MIN = 0.70


def _float(v) -> float | None:
    return None if v is None else float(v)


def _entity_key(row: dict) -> tuple:
    return row["id_medication"], row["nr_entity_id"]


def _parsed(responses: Iterable[tuple[int, str | None]]):
    for id_medication, raw in sorted(responses, key=lambda r: r[0]):
        try:
            doc = json.loads(raw)  # type: ignore[arg-type]
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(doc, dict):
            yield id_medication, doc


def entity_icd_rows(responses: Iterable[tuple[int, str | None]]) -> list[dict]:
    """`hd_int_med_disease_entity_icd`: upsert on (med, entity Id, code), last wins; PK order."""
    out: dict[tuple, dict] = {}
    for med, doc in _parsed(responses):
        for idx, entity in enumerate(doc.get("Entities", []) or [], start=1):
            eid = entity.get("Id")
            if eid is None:
                eid = idx
            attrs = json.dumps(entity.get("Attributes", []), ensure_ascii=False)
            for icd in entity.get("ICD10CMConcepts", []) or []:
                code = icd.get("Code")
                if not code:
                    continue
                out[(med, eid, code)] = {
                    "id_medication": med,
                    "nr_entity_id": eid,
                    "ds_entity_text": entity.get("Text") or "",
                    "tp_entity": entity.get("Type"),
                    "ds_category": entity.get("Category"),
                    "vl_entity_score": _float(entity.get("Score")),
                    "nr_begin_offset": entity.get("BeginOffset"),
                    "nr_end_offset": entity.get("EndOffset"),
                    "ds_attributes": attrs,
                    "cd_icd_full": code,
                    "ds_icd": icd.get("Description"),
                    "vl_icd_score": _float(icd.get("Score")),
                }
    return sorted(out.values(), key=lambda r: (r["id_medication"], r["nr_entity_id"], collation_key(r["cd_icd_full"])))


def entity_trait_rows(responses: Iterable[tuple[int, str | None]]) -> list[dict]:
    """`hd_int_med_disease_entity_trait`: upsert on (med, entity Id, name); independent of concepts."""
    out: dict[tuple, dict] = {}
    for med, doc in _parsed(responses):
        for idx, entity in enumerate(doc.get("Entities", []) or [], start=1):
            eid = entity.get("Id")
            if eid is None:
                eid = idx
            for tr in entity.get("Traits", []) or []:
                name = tr.get("Name")
                if not name:
                    continue
                out[(med, eid, name)] = {
                    "id_medication": med,
                    "nr_entity_id": eid,
                    "nm_trait": name,
                    "vl_trait_score": _float(tr.get("Score")),
                }
    return sorted(out.values(), key=lambda r: (r["id_medication"], r["nr_entity_id"], collation_key(r["nm_trait"])))


def _level(score: float | None) -> str:
    if score is not None and score >= ICD_HIGH_MIN:
        return "HIGH"
    if score is not None and score >= ICD_MEDIUM_MIN:
        return "MEDIUM"
    return "LOW"


def _and(*vals: int | None) -> int | None:
    """SQL three-valued AND over 0/1/NULL."""
    if any(v == 0 for v in vals):
        return 0
    return None if any(v is None for v in vals) else 1


def cutoff_audit_rows(entity_icd: list[dict], entity_trait: list[dict], hier: Hierarchy) -> list[dict]:
    """`hd_int_med_disease_cutoff_audit`: top-1 concept per (med, entity Id), in PK order."""
    top: dict[tuple, dict] = {}
    for r in entity_icd:
        k = _entity_key(r)
        cur = top.get(k)
        if cur is None or _rank(r) < _rank(cur):
            top[k] = r
    traits: dict[tuple, list[tuple[str, float | None]]] = {}
    for t in entity_trait:
        traits.setdefault(_entity_key(t), []).append((t["nm_trait"], t["vl_trait_score"]))

    out = []
    for k in sorted(top):
        r = top[k]
        tl = traits.get(k)
        if tl:
            ordered = sorted(tl, key=lambda t: (-(t[1] or 0.0), collation_key(t[0])))
            main_name: str | None = ordered[0][0]
            main_score: float | None = max(t[1] or 0.0 for t in tl)
            negation = int(any(name.upper() == "NEGATION" for name, _ in tl))
        else:
            main_name = main_score = None
            negation = 0
        code = r["cd_icd_full"]
        nodot = mapping.nodot(code)
        mapped, map_type = mapping.who_map(hier, code, "exact_fb")
        group, cat, sub = mapping.v2_ids(hier, code)
        es = r["vl_entity_score"]
        dx = None if r["tp_entity"] is None else int(r["tp_entity"] == "DX_NAME")
        pass_neg = int(negation == 0)
        pass_es = None if es is None else int(es >= ENTITY_SCORE_MIN)
        out.append({
            "id_medication": k[0],
            "nr_entity_id": k[1],
            "ds_entity_text": r["ds_entity_text"],
            "tp_entity": r["tp_entity"],
            "ds_category": r["ds_category"],
            "vl_entity_score": es,
            "nr_begin_offset": r["nr_begin_offset"],
            "nr_end_offset": r["nr_end_offset"],
            "ds_attributes": r["ds_attributes"],
            "cd_icd10cm_full": code,
            "cd_icd10cm_nodot": nodot,
            "ds_icd10cm": r["ds_icd"],
            "vl_icd10cm_score": r["vl_icd_score"],
            "tp_icd10cm_score_level": _level(r["vl_icd_score"]),
            "fl_negation": negation,
            "nm_trait_main": main_name,
            "vl_trait_main_score": main_score,
            "cd_icd10_nodot": mapped,
            "tp_icd10_map": map_type,
            "id_icd_group": group,
            "id_icd_cat": cat,
            "id_icd_subcat": sub,
            "fl_pass_dx_name": dx,
            "fl_pass_negation": pass_neg,
            "fl_pass_entity_score": pass_es,
            "fl_pass_all_pre": _and(dx, pass_neg, pass_es),
        })
    return out


def _rank(r: dict) -> tuple:
    """ROW_NUMBER order: vl_icd_score DESC (NULL last), then code collation."""
    s = r["vl_icd_score"]
    return s is None, -(s or 0.0), collation_key(r["cd_icd_full"])


def _desc(v: float | None) -> tuple[bool, float]:
    return v is None, -(v or 0.0)


def md_rows(audit: list[dict], hier: Hierarchy) -> list[dict]:
    """`hd_medication_disease`: dedup by (med, mapped WHO code), keep MEDIUM/HIGH; ids 1..n in key order.

    `hier` is accepted for symmetry with the other builders; the audit rows already carry the mapping.
    Each output row has an extra `tie_flag` (not a dump column): the best row of its group is not unique
    under ORDER BY vl_icd10cm_score DESC, vl_entity_score DESC, so GROUP_CONCAT order is undefined there.
    """
    del hier
    groups: dict[tuple, list[dict]] = {}
    for a in audit:  # audit PK order: the order MySQL would feed the group (undefined, this is our choice)
        if a["fl_pass_all_pre"] == 1 and a["cd_icd10_nodot"] is not None:
            groups.setdefault((a["id_medication"], a["cd_icd10_nodot"]), []).append(a)

    out = []
    for (med, code), rows in sorted(groups.items(), key=lambda g: (g[0][0], collation_key(g[0][1]))):
        score = max((r["vl_icd10cm_score"] for r in rows if r["vl_icd10cm_score"] is not None), default=None)
        level = _level(score)
        if level == "LOW":
            continue
        ordered = sorted(rows, key=lambda r: (_desc(r["vl_icd10cm_score"]), _desc(r["vl_entity_score"])))
        best = ordered[0]
        # GROUP_CONCAT skips NULLs but COALESCE(vl_trait_main_score, 0) does not: the name may come from
        # a later row than the score (documented misalignment).
        names = [r["nm_trait_main"] for r in ordered if r["nm_trait_main"] is not None]
        es = [r["vl_entity_score"] for r in ordered if r["vl_entity_score"] is not None]
        ties = sum(
            1 for r in rows
            if (r["vl_icd10cm_score"], r["vl_entity_score"]) == (best["vl_icd10cm_score"], best["vl_entity_score"])
        )

        def top_id(col: str) -> int | None:
            return max((r[col] for r in rows if r[col] is not None), default=None)

        out.append({
            "id_med_disease": len(out) + 1,
            "id_medication": med,
            "cd_icd_full": code,
            "id_icd_group": top_id("id_icd_group"),
            "id_icd_cat": top_id("id_icd_cat"),
            "id_icd_subcat": top_id("id_icd_subcat"),
            "vl_entity_score": es[0] if es else None,
            "vl_icd_score": score,
            "tp_icd_score": level,
            "nm_trait_main": names[0] if names else None,
            "vl_trait_main_score": best["vl_trait_main_score"] or 0.0,
            "tie_flag": ties > 1,
        })
    return out
