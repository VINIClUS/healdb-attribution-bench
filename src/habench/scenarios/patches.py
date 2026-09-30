"""Semisynthetic patches (SPEC 4.5): the five operations and the invariant validators.

A patch edits the parsed response of one medication (paths inside `Entities`). Entities are addressed by
array position, which is unambiguous when an `Id` repeats. Every constructor validates its result and raises
`PatchError` on an edit that violates an invariant of a real response:
- the number of concepts per entity does not change;
- concepts stay in descending score order, with no tie at the top;
- scores stay in [0, 1];
- entity `Id`s stay unique, unless a duplicate already existed;
- patches of one contrast edit disjoint (entity, field) targets.
Violations are measured against the original document: a property the real response already lacks is not
blamed on the edit. Patch ids are opaque ("p" + short hash of the edit content).
"""

from __future__ import annotations

import copy
import json
import math
import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from itertools import combinations

from habench.pipeline.evidence import JsonEdit, Patch, apply_edits, validate_response
from habench.scenarios.ids import opaque_id

Docs = Mapping[int, dict]
Target = tuple[int, int, str]  # (med, entity position, field); field "*" covers the whole entity
_PREFIX = re.compile(r"^entity \d+: ")
RANGE_PROBLEM = "score outside [0, 1]"


class PatchError(ValueError):
    """The edit violates an invariant of SPEC 4.5."""


class HashableDict(dict):
    """A dict usable as `JsonEdit.value`: `Patch` is hashed by `Evidence.patched`, and plain dicts do not hash."""

    def __hash__(self) -> int:  # type: ignore[override]
        return hash(json.dumps(self, sort_keys=True, separators=(",", ":")))


class HashableList(list):
    def __hash__(self) -> int:  # type: ignore[override]
        return hash(json.dumps(self, sort_keys=True, separators=(",", ":")))


def freeze(value: object) -> object:
    """Recursively replace lists and dicts by their hashable subclasses (scalars unchanged)."""
    if isinstance(value, dict):
        return HashableDict({k: freeze(v) for k, v in value.items()})
    if isinstance(value, list):
        return HashableList(freeze(v) for v in value)
    return value


def freeze_patch(patch: Patch) -> Patch:
    """The same patch with hashable edit values (needed after `Contrast.from_json`, which yields plain lists)."""
    return Patch(patch.id, tuple(JsonEdit(e.med, e.path, freeze(e.value)) for e in patch.edits))


# ---------------------------------------------------------------------- invariants


def _entity_problems(ent: dict) -> list[str]:
    out = []
    concepts = ent.get("ICD10CMConcepts") or []
    scores = [c.get("Score") for c in concepts]
    if scores != sorted(scores, reverse=True):
        out.append("concepts not in descending score order")
    if len(scores) > 1 and scores[0] == scores[1]:
        out.append("tie at the top concept")
    for s in [ent.get("Score"), *scores, *(t.get("Score") for t in ent.get("Traits") or [])]:
        if s is not None and (isinstance(s, bool) or not isinstance(s, (int, float)) or not 0.0 <= s <= 1.0):
            out.append(RANGE_PROBLEM)
    return out


def concept_count_violations(orig: dict, edited: dict) -> list[str]:
    o, e = orig.get("Entities") or [], edited.get("Entities") or []
    if len(o) != len(e):
        return ["number of entities changed"]
    key = lambda ents: Counter((x.get("Id"), len(x.get("ICD10CMConcepts") or [])) for x in ents)  # noqa: E731
    return [] if key(o) == key(e) else ["number of concepts per entity changed"]


def order_violations(orig: dict, edited: dict) -> list[str]:
    """New descending-order or top-tie problems (per entity, position independent)."""
    new = _new_problems(orig, edited, lambda ent: [p for p in _entity_problems(ent) if p != RANGE_PROBLEM])
    return [f"{p} (new)" for p in new]


def range_violations(orig: dict, edited: dict) -> list[str]:
    new = _new_problems(orig, edited, lambda ent: [p for p in _entity_problems(ent) if p == RANGE_PROBLEM])
    return [f"{p} (new)" for p in new]


def _new_problems(orig: dict, edited: dict, fn) -> list[str]:
    before = Counter(p for ent in orig.get("Entities") or [] for p in fn(ent))
    after = Counter(p for ent in edited.get("Entities") or [] for p in fn(ent))
    return sorted((after - before).elements())


def id_violations(orig: dict, edited: dict) -> list[str]:
    before = Counter(e.get("Id") for e in orig.get("Entities") or [])
    after = Counter(e.get("Id") for e in edited.get("Entities") or [])
    bad = sorted(str(i) for i, n in after.items() if n > max(1, before.get(i, 0)))
    return [f"entity Id repeated: {i}" for i in bad]


def response_violations(orig: dict, edited: dict) -> list[str]:
    """`evidence.validate_response` problems that the edit introduced (index prefix stripped)."""
    norm = lambda doc: Counter(_PREFIX.sub("", p) for p in validate_response(doc))  # noqa: E731
    return sorted((norm(edited) - norm(orig)).elements())


def violations(orig: dict, edited: dict) -> list[str]:
    """Every SPEC 4.5 violation introduced by the edit (empty list: valid)."""
    return [
        *concept_count_violations(orig, edited),
        *order_violations(orig, edited),
        *range_violations(orig, edited),
        *id_violations(orig, edited),
        *response_violations(orig, edited),
    ]


# ---------------------------------------------------------------------- targets and validation


def targets(patch: Patch) -> frozenset[Target]:
    out = set()
    for e in patch.edits:
        if e.path[0] != "Entities" or len(e.path) < 2:
            raise PatchError(f"unsupported edit path {e.path}")
        out.add((e.med, int(e.path[1]), "*" if len(e.path) == 2 else str(e.path[2])))
    return frozenset(out)


def _overlap(a: Target, b: Target) -> bool:
    return a[:2] == b[:2] and (a[2] == b[2] or "*" in (a[2], b[2]))


def check_disjoint(patches: Sequence[Patch]) -> None:
    for p, q in combinations(patches, 2):
        if any(_overlap(a, b) for a in targets(p) for b in targets(q)):
            raise PatchError("patches edit overlapping (entity, field) targets")


def _docs_of(docs: Docs, patches: Iterable[Patch]) -> dict[int, dict]:
    meds = {m for p in patches for m in p.meds}
    missing = sorted(meds - set(docs))
    if missing:
        raise PatchError(f"no stored response for medications {missing}")
    return {m: docs[m] for m in meds}


def check_patch(docs: Docs, patch: Patch) -> None:
    """Raise PatchError if `patch` alone violates an invariant."""
    check_patches(docs, [patch])


def check_patches(docs: Docs, patches: Sequence[Patch]) -> None:
    """Disjoint targets, plus the invariants on the result of every subset of the patches (hybrids apply any)."""
    check_disjoint(patches)
    base = _docs_of(docs, patches)
    for r in range(1, len(patches) + 1):
        for sub in combinations(patches, r):
            for med, doc in base.items():
                edits = [e for p in sub for e in p.edits if e.med == med]
                if not edits:
                    continue
                try:
                    edited = apply_edits(doc, edits)
                except (KeyError, IndexError, TypeError) as exc:
                    raise PatchError(f"edit path does not exist: {exc!r}") from exc
                bad = violations(doc, edited)
                if bad:
                    raise PatchError("; ".join(bad))


# ---------------------------------------------------------------------- operations


def patch_id(edits: Sequence[JsonEdit]) -> str:
    body = json.dumps([[e.med, list(e.path), e.value] for e in edits], sort_keys=True, separators=(",", ":"),
                      allow_nan=False)
    return opaque_id("p", body, n=10)


def _finish(docs: Docs, edits: tuple[JsonEdit, ...]) -> Patch:
    p = freeze_patch(Patch(patch_id(edits), edits))
    doc = _docs_of(docs, [p])[edits[0].med]
    if apply_edits(doc, edits) == doc:
        raise PatchError("the edit changes nothing")
    check_patch(docs, p)
    return p


def _entity(docs: Docs, med: int, pos: int) -> dict:
    if med not in docs:
        raise PatchError(f"no stored response for medication {med}")
    ents = docs[med].get("Entities") or []
    if not 0 <= pos < len(ents):
        raise PatchError(f"medication {med} has no entity at position {pos}")
    return ents[pos]


def _score(value: float) -> float:
    v = float(value)
    if not math.isfinite(v) or not 0.0 <= v <= 1.0:
        raise PatchError(f"score {value!r} outside [0, 1]")
    return v


def set_entity_score(docs: Docs, med: int, entity: int, value: float) -> Patch:
    _entity(docs, med, entity)
    return _finish(docs, (JsonEdit(med, ("Entities", entity, "Score"), _score(value)),))


def set_concept_score(docs: Docs, med: int, entity: int, code: str, value: float) -> Patch:
    concepts = _entity(docs, med, entity).get("ICD10CMConcepts") or []
    at = [j for j, c in enumerate(concepts) if c.get("Code") == code]
    if len(at) != 1:
        raise PatchError(f"entity {entity} has {len(at)} concepts with code {code}")
    return _finish(docs, (JsonEdit(med, ("Entities", entity, "ICD10CMConcepts", at[0], "Score"), _score(value)),))


def add_trait(docs: Docs, med: int, entity: int, name: str, score: float) -> Patch:
    traits = copy.deepcopy(_entity(docs, med, entity).get("Traits") or [])
    if any(t.get("Name") == name for t in traits):
        raise PatchError(f"entity {entity} already has trait {name}")
    traits.append({"Name": name, "Score": _score(score)})
    return _finish(docs, (JsonEdit(med, ("Entities", entity, "Traits"), traits),))


def remove_trait(docs: Docs, med: int, entity: int, name: str) -> Patch:
    traits = _entity(docs, med, entity).get("Traits") or []
    kept = [copy.deepcopy(t) for t in traits if t.get("Name") != name]
    if len(kept) == len(traits):
        raise PatchError(f"entity {entity} has no trait {name}")
    return _finish(docs, (JsonEdit(med, ("Entities", entity, "Traits"), kept),))


def swap_entities(docs: Docs, med: int, a: int, b: int) -> Patch:
    if a == b:
        raise PatchError("swap of an entity with itself")
    _entity(docs, med, a), _entity(docs, med, b)
    lo, hi = sorted((a, b))
    return _finish(docs, (
        JsonEdit(med, ("Entities", lo), copy.deepcopy(_entity(docs, med, hi))),
        JsonEdit(med, ("Entities", hi), copy.deepcopy(_entity(docs, med, lo))),
    ))
