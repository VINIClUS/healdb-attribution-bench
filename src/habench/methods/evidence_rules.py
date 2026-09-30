"""Method-side reading of visible evidence and sound irrelevance rules (SPEC 4.6, 4.3).

The method process cannot import the core, so these rules work on the parsed ACM responses with a
*superset* of the relevant candidates of an association: every concept of the medication whose code, without
the dot, starts with the key's code (WHO space) or equals it (CM space). A superset only makes the rules more
conservative. Every rule may answer False when unsure; none may answer True wrongly.

Level-pair and variant irrelevance ("pair rules") decide whether a factor whose executed level or variant is not
observable could still change the state of an association (SPEC 4.3 hypotheses):
- thresholds: `>= t` versus `> t` differ only for a relevant score exactly at t;
- `trait = v1` versus its pair `v1_hyp_le_0.6`: only for a HYPOTHETICAL score in (0.60, 0.65] on an entity of
  the medication;
- `occ = last_upsert` versus `first_upsert`: only when a relevant code has two or more candidates;
- `map = cm_gated` versus `cm_ungated`: never in the WHO space (a code without projection fails the gate or is
  unmapped, and produces no key either way, SPEC 1.3); unknown in the CM space.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass

from habench.types import SYSTEM_ICD10CM, AssocKey

THRESHOLDS = ("ent_thr", "icd_thr")
PAIRS = {
    ("trait", "v1"): "v1_hyp_le_0.6",
    ("trait", "v1_hyp_le_0.6"): "v1",
    ("occ", "last_upsert"): "first_upsert",
    ("occ", "first_upsert"): "last_upsert",
    ("map", "cm_gated"): "cm_ungated",
    ("map", "cm_ungated"): "cm_gated",
}
# Levels whose implementation may run the `alt` variant (SPEC 4.3); thresholds: every level.
ALT_LEVELS = {("trait", "v1"), ("occ", "last_upsert"), ("map", "cm_gated")}
HYP_BAND = (0.60, 0.65)


@dataclass(frozen=True, slots=True)
class Cand:
    entity: int  # position in the Entities array
    eid: int
    code: str
    es: float
    cs: float


@dataclass(frozen=True, slots=True)
class MedDoc:
    """One medication's parsed response as the method sees it."""

    cands: tuple[Cand, ...]
    hyps: tuple[float, ...]  # HYPOTHETICAL scores of every entity (missing score counts as 0, SPEC 3.1)
    top1: bool  # only the first concept of each entity is visible (ablation A2)

    @classmethod
    def parse(cls, raw: str | None, *, top1: bool) -> MedDoc | None:
        if raw is None:
            return None
        try:
            doc = json.loads(raw)
        except json.JSONDecodeError:
            return None
        if not isinstance(doc, dict):
            return None
        cands, hyps = [], []
        for pos, ent in enumerate(doc.get("Entities") or []):
            eid = ent.get("Id", pos + 1)
            for t in ent.get("Traits") or []:
                if t.get("Name") == "HYPOTHETICAL":
                    hyps.append(float(t.get("Score") or 0.0))
            for con in ent.get("ICD10CMConcepts") or []:
                if con.get("Code"):
                    cands.append(Cand(pos, eid, con["Code"], float(ent.get("Score")), float(con.get("Score"))))
        return cls(tuple(cands), tuple(hyps), top1)


def relevant(doc: MedDoc, key: AssocKey) -> list[Cand]:
    if key.system == SYSTEM_ICD10CM:
        return [c for c in doc.cands if c.code == key.code]
    return [c for c in doc.cands if c.code.replace(".", "").startswith(key.code)]


def _floats(levels: tuple[str, str]) -> tuple[float, float] | None:
    try:
        return float(levels[0]), float(levels[1])
    except ValueError:
        return None


class Evidence:
    """The x0 and x1 responses visible in the view, per medication."""

    def __init__(self, x0: Mapping[int, MedDoc | None], x1: Mapping[int, MedDoc | None], raw_equal: Mapping[int, bool]):
        self.x0, self.x1, self.raw_equal = x0, x1, raw_equal

    def docs(self, med: int) -> list[MedDoc] | None:
        """Both runs' documents (patch variants: each edited field takes its x0 or its x1 value, SPEC 4.5)."""
        d0, d1 = self.x0.get(med), self.x1.get(med)
        if d0 is None or d1 is None:
            return None
        return [d0, d1]

    # ------------------------------------------------------------------ dummy certificates (SPEC 4.6)

    def dummy(self, f: str, key: AssocKey, levels: tuple[str, str] | None, patch_handles: frozenset[str]) -> bool:
        """Sound, incomplete `dummy(f, key)` for a member f of D with declared/executed levels (x0, x1)."""
        docs = self.docs(key.med)
        if docs is None:
            return False
        if f in patch_handles:
            # Rule 0: no patch edits this medication when its x0 and x1 responses are byte-identical.
            return self.raw_equal.get(key.med, False) and not docs[0].top1
        if f in THRESHOLDS and levels is not None:
            t = _floats(levels)
            if t is None or any(d.top1 for d in docs):
                return False
            lo, hi = min(t), max(t)
            # Rule 1 on the closed band, which also covers the `>` variant at either level.
            return not any(lo <= (c.es if f == "ent_thr" else c.cs) <= hi for d in docs for c in relevant(d, key))
        return False

    # ------------------------------------------------------------------ pair / variant irrelevance (SPEC 4.3)

    def pair_irrelevant(self, f: str, level: str, key: AssocKey) -> bool:
        """Whether running `level` or its pair/alt variant cannot change the state of `key`."""
        if f == "map":
            return key.system != SYSTEM_ICD10CM
        docs = self.docs(key.med)
        if docs is None:
            return False
        if f in THRESHOLDS:
            try:
                t = float(level)
            except ValueError:
                return False
            if f == "icd_thr" and any(d.top1 for d in docs):
                return False
            if f == "ent_thr":  # entity scores are all visible even under top-1: use every entity
                return not any(c.es == t for d in docs for c in d.cands)
            return not any(c.cs == t for d in docs for c in relevant(d, key))
        if f == "trait":
            lo, hi = HYP_BAND
            return not any(lo < h <= hi for d in docs for h in d.hyps)
        if f == "occ":
            if any(d.top1 for d in docs):
                return False
            for d in docs:
                codes = [c.code for c in relevant(d, key)]
                if len(codes) != len(set(codes)):
                    return False
            return True
        return False
