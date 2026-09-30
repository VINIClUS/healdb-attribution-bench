"""V1 intermediate tables rebuilt from V1 ACM responses (process_disease_data_json.py @405a10c)."""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator

import numpy as np

from habench.pipeline import core, mapping
from habench.pipeline.catalog import ATTRIBUTE_KNOBS, V1, V1_EXTEND, Config
from habench.pipeline.evidence import Evidence, collation_key
from habench.pipeline.mapping import Hierarchy

ENTITY_COLUMNS = (
    "id_medication",
    "cd_icd_full",
    "ds_icd",
    "vl_score",
    "ds_icd_aggreg",
    "vl_entity_score",
    "tp_category",
    "nr_begin_offset",
    "nr_end_offset",
    "tp_entity",
    "ds_attributes",
)


MD_COLUMNS = (
    "id_med_disease",
    "id_medication",
    "cd_icd_full",
    "id_icd_group",
    "id_icd_cat",
    "id_icd_subcat",
    "vl_score",
    "vl_entity_score",
    "fl_low_confidence",
    "nm_trait_main",
    "vl_trait_main_score",
)
EXTEND_FIRST_ID = 23_302  # AUTO_INCREMENT fitted to the V1 data (F1 §2.4): inferred, not historical


def _md_like(ev: Evidence, hier: Hierarchy, cfg: Config, ids, first_id: int) -> list[dict]:
    """link@405a10c: iterate (med, code) in entity PK order, filter, insert with AUTO_INCREMENT ids."""
    e = core.evaluate(cfg, ev, hier)
    rec = e.records
    order = sorted(np.flatnonzero(e.passed), key=lambda i: (int(rec.med[i]), collation_key(ev.codes[rec.code[i]])))
    low = ATTRIBUTE_KNOBS["low_conf_thr"]
    out = []
    for n, i in enumerate(order):
        code = ev.codes[rec.code[i]]
        # LEFT JOIN order is the trait PK order; the stable sort keeps it on score ties (PROV §2.2)
        traits = sorted(rec.traits[i].items(), key=lambda t: collation_key(t[0]))
        name, score = sorted(traits, key=lambda t: t[1] or 0, reverse=True)[0] if traits else (None, None)
        cs, es = float(rec.cs[i]), float(rec.es[i])
        group, cat, sub = ids(hier, code)
        out.append({
            "id_med_disease": first_id + n,
            "id_medication": int(rec.med[i]),
            "cd_icd_full": code,
            "id_icd_group": group,
            "id_icd_cat": cat,
            "id_icd_subcat": sub,
            "vl_score": cs,
            "vl_entity_score": es,
            "fl_low_confidence": int(cs < low or es < low),
            "nm_trait_main": name,
            "vl_trait_main_score": score,
        })
    return out


def md_rows(ev: Evidence, hier: Hierarchy) -> list[dict]:
    """V1 `hd_medication_disease` (ids 1..n, operator TRUNCATE assumed before the run)."""
    return _md_like(ev, hier, V1, mapping.v1_ids, 1)


def extend_rows(ev: Evidence, hier: Hierarchy) -> list[dict]:
    """V1 `hd_medication_disease_extend` by the inferred rule (no gate, inferred id search, fitted first id)."""
    return _md_like(ev, hier, V1_EXTEND, mapping.extend_ids, EXTEND_FIRST_ID)


def _parsed(responses: Iterable[tuple[int, str | None]]) -> Iterator[tuple[int, dict]]:
    for id_medication, raw in sorted(responses, key=lambda r: r[0]):
        try:
            doc = json.loads(raw)  # type: ignore[arg-type]
        except (json.JSONDecodeError, TypeError):
            continue
        yield id_medication, doc


def _extract(
    responses: Iterable[tuple[int, str | None]],
) -> tuple[dict[tuple, dict], dict[tuple, dict]]:
    entities: dict[tuple, dict] = {}
    traits: dict[tuple, dict] = {}
    for id_medication, doc in _parsed(responses):
        for entity in doc.get("Entities", []):
            attributes = json.dumps(entity.get("Attributes", []))
            for concept in entity.get("ICD10CMConcepts", []):
                code = concept.get("Code")
                entities[(id_medication, code)] = {
                    "id_medication": id_medication,
                    "cd_icd_full": code,
                    "ds_icd": concept.get("Description"),
                    "vl_score": concept.get("Score"),
                    "ds_icd_aggreg": entity.get("Text"),
                    "vl_entity_score": entity.get("Score"),
                    "tp_category": entity.get("Category"),
                    "nr_begin_offset": entity.get("BeginOffset"),
                    "nr_end_offset": entity.get("EndOffset"),
                    "tp_entity": entity.get("Type"),
                    "ds_attributes": attributes,
                }
                for trait in entity.get("Traits", []):
                    name = trait.get("Name")
                    traits[(id_medication, code, name)] = {
                        "id_medication": id_medication,
                        "cd_icd_full": code,
                        "nm_trait": name,
                        "vl_trait_score": trait.get("Score"),
                    }
    return entities, traits


def entity_rows(responses: Iterable[tuple[int, str | None]]) -> list[dict]:
    entities, _ = _extract(responses)
    return sorted(entities.values(), key=lambda r: (r["id_medication"], collation_key(r["cd_icd_full"])))


def trait_rows(responses: Iterable[tuple[int, str | None]]) -> list[dict]:
    _, traits = _extract(responses)
    return sorted(
        traits.values(),
        key=lambda r: (r["id_medication"], collation_key(r["cd_icd_full"]), collation_key(r["nm_trait"])),
    )


def compare_rows(
    ours: list[dict],
    theirs: list[dict],
    key: tuple[str, ...],
    json_columns: tuple[str, ...] = ("ds_attributes",),
) -> dict:
    """Compare two row lists by primary key; exact values except JSON columns (parsed)."""

    def k(row: dict) -> tuple:
        return tuple(row[c] for c in key)

    def norm(col: str, v):
        if col in json_columns and isinstance(v, str):
            return json.loads(v)
        return v

    def same(a, b) -> bool:
        # exact: type-sensitive so 1 != 1.0 and True != 1 are reported
        return type(a) is type(b) and a == b if not isinstance(a, (list, dict)) else _json_same(a, b)

    def _json_same(a, b) -> bool:
        if isinstance(a, dict) and isinstance(b, dict):
            return a.keys() == b.keys() and all(_json_same(a[x], b[x]) for x in a)
        if isinstance(a, list) and isinstance(b, list):
            return len(a) == len(b) and all(_json_same(x, y) for x, y in zip(a, b, strict=True))
        return type(a) is type(b) and a == b

    ours_by = {k(r): r for r in ours}
    theirs_by = {k(r): r for r in theirs}
    only_ours = [x for x in ours_by if x not in theirs_by]
    only_theirs = [x for x in theirs_by if x not in ours_by]
    differ = []
    for kk, ro in ours_by.items():
        rt = theirs_by.get(kk)
        if rt is None:
            continue
        for col in sorted(ro.keys() | rt.keys()):
            a, b = norm(col, ro.get(col)), norm(col, rt.get(col))
            if not same(a, b):
                differ.append((kk, col, ro.get(col), rt.get(col)))
    return {
        "n_ours": len(ours),
        "n_theirs": len(theirs),
        "only_ours": only_ours,
        "only_theirs": only_theirs,
        "differ": differ,
        "order_equal": [k(r) for r in ours] == [k(r) for r in theirs],
    }
