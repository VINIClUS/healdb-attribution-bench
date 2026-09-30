"""ICD hierarchy lookups: the V1 gate and id search, the inferred extend search, and V2's WHO mapping.

Codes from ACM are dotted ICD-10-CM. The HealDB hierarchy holds dotless WHO ICD-10 categories
(3 characters) and subcategories (4 characters). MySQL compares under a case-insensitive
collation; ACM codes are uppercase, so exact dictionary lookups are equivalent here.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass

MAP_SUBCAT_EXACT = "SUBCAT_EXACT"
MAP_CAT3_FALLBACK = "CAT3_FALLBACK"
MAP_CAT_EXACT = "CAT_EXACT"
MAP_NO_MAP = "NO_MAP"


@dataclass(frozen=True)
class Hierarchy:
    cat: Mapping[str, tuple[int, int]]  # cd_cat -> (id_cat, id_group)
    subcat: Mapping[str, tuple[int, int]]  # cd_subcat -> (id_subcat, id_cat)
    group_of_cat: Mapping[int, int]  # id_cat -> id_group
    sha256: str  # of the canonical rows, not of the dump bytes

    @property
    def version(self) -> str:
        return f"hier:{self.sha256[:16]}"

    @classmethod
    def from_rows(cls, categories: list[dict], subcategories: list[dict]) -> Hierarchy:
        cat = {r["cd_cat"]: (r["id_cat"], r["id_group"]) for r in categories}
        subcat = {r["cd_subcat"]: (r["id_subcat"], r["id_cat"]) for r in subcategories}
        canon = json.dumps(
            {"cat": sorted([k, *v] for k, v in cat.items()), "subcat": sorted([k, *v] for k, v in subcat.items())},
            separators=(",", ":"),
        )
        return cls(
            cat=cat,
            subcat=subcat,
            group_of_cat={r["id_cat"]: r["id_group"] for r in categories},
            sha256=hashlib.sha256(canon.encode()).hexdigest(),
        )


def load_hierarchy(snap: str = "v1") -> Hierarchy:
    from habench.data.store import load_records

    return Hierarchy.from_rows(
        load_records(snap, "hd_icd_category", ["id_cat", "id_group", "cd_cat"]),
        load_records(snap, "hd_icd_subcategory", ["id_subcat", "id_cat", "cd_subcat"]),
    )


def nodot(code: str) -> str:
    return code.replace(".", "")


def v1_gate(h: Hierarchy, code: str) -> bool:
    """link@405a10c lines 111-132: dotless code is a category or subcategory, else its 3-char prefix is a category."""
    nd = nodot(code)
    if nd in h.cat or nd in h.subcat:
        return True
    return len(nd) >= 3 and nd[:3] in h.cat


def v1_ids(h: Hierarchy, code: str) -> tuple[int | None, int | None, int | None]:
    """search_repository_icd@405a10c: category of the 3-char prefix, overridden by an exact subcategory."""
    nd = nodot(code)
    group = cat = sub = None
    if nd[:3] in h.cat:
        cat, group = h.cat[nd[:3]]
    if nd in h.subcat:
        sub, cat = h.subcat[nd]
        group = h.group_of_cat[cat]
    return group, cat, sub


def extend_ids(h: Hierarchy, code: str) -> tuple[int | None, int | None, int | None]:
    """Inferred search of `extend` (workspace patch, changes 2 and 4; fitted to the V1 data, F1 §2.4).

    Category and subcategory are looked up independently by the whole dotless code; only when both
    miss is the 3-char prefix used as a category.
    """
    nd = nodot(code)
    group = cat = sub = None
    if nd in h.cat:
        cat, group = h.cat[nd]
    if nd in h.subcat:
        sub = h.subcat[nd][0]
    if cat is None and sub is None and nd[:3] in h.cat:
        cat, group = h.cat[nd[:3]]
    return group, cat, sub


def who_map(h: Hierarchy, code: str, policy: str = "exact_fb") -> tuple[str | None, str]:
    """Project an ICD-10-CM code to a dotless WHO ICD-10 code.

    - `exact_fb` (V2 HEAD lines 134-184): exact subcategory, else category of the 3-char prefix.
      A 3-char code equal to a category is labelled CAT3_FALLBACK, like V2.
    - `exact`: exact subcategory, or exact category for a 3-char code; no prefix fallback.
    - `cat3`: category of the 3-char prefix (projection to category, not a validated translation).
    Returns (mapped code or None, map type).
    """
    nd = nodot(code)
    if policy == "exact_fb":
        if nd in h.subcat:
            return nd, MAP_SUBCAT_EXACT
        if nd[:3] in h.cat:
            return nd[:3], MAP_CAT3_FALLBACK
        return None, MAP_NO_MAP
    if policy == "exact":
        if nd in h.subcat:
            return nd, MAP_SUBCAT_EXACT
        if nd in h.cat:
            return nd, MAP_CAT_EXACT
        return None, MAP_NO_MAP
    if policy == "cat3":
        if nd[:3] in h.cat:
            return nd[:3], MAP_CAT3_FALLBACK
        return None, MAP_NO_MAP
    raise ValueError(f"unknown WHO mapping policy {policy!r}")


def v2_ids(h: Hierarchy, code: str) -> tuple[int | None, int | None, int | None]:
    """V2 HEAD lines 166-175: COALESCE(subcat's category, cat3) ids; subcat id only on an exact match."""
    nd = nodot(code)
    if nd in h.subcat:
        sub, cat = h.subcat[nd]
        return h.group_of_cat[cat], cat, sub
    if nd[:3] in h.cat:
        cat, group = h.cat[nd[:3]]
        return group, cat, None
    return None, None, None
