"""Parsed ACM responses as columnar candidate evidence, array order preserved (never sorted).

A candidate is one (entity occurrence, ICD-10-CM concept) pair of a response, in the order the
response lists them: entities in array order, concepts in array order inside each entity.
Semisynthetic edits of a response are `Patch` objects; they are applied to the parsed JSON and
flagged by their factor name (`patch:<id>`), never silently.
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

import numpy as np

STATUS_OK = "ok"  # valid response with at least one entity
STATUS_EMPTY = "empty"  # valid response without entities: a real execution, associations are ABSENT
STATUS_FAILED = "failed"  # NULL or undecodable response: UNAVAILABLE, never ABSENT
STATUS_MISSING = "missing"  # no response row for the medication: UNAVAILABLE

TRANSPORT_KEY = "ResponseMetadata"


def collation_key(s: str) -> tuple[tuple[int, str], ...]:
    """Sort key matching MySQL utf8mb4_0900_ai_ci on ICD codes and trait names.

    '_' and '.' sort before digits, digits before letters, letters case-insensitively. Other
    characters raise, so an unmodelled character cannot silently change an order.
    """
    out = []
    for ch in s:
        if ch == "_":
            out.append((0, "0"))
        elif ch == ".":
            out.append((0, "1"))
        elif "0" <= ch <= "9":
            out.append((1, ch))
        elif ch.isascii() and "A" <= ch.upper() <= "Z":
            out.append((2, ch.upper()))
        else:
            raise ValueError(f"collation_key: unsupported character {ch!r} in {s!r}")
    return tuple(out)


@dataclass(frozen=True, slots=True)
class JsonEdit:
    """Set the value at `path` (keys and list indexes) inside the parsed response of `med`."""

    med: int
    path: tuple[str | int, ...]
    value: object


@dataclass(frozen=True, slots=True)
class Patch:
    """A semisynthetic evidence edit, exposed as the binary factor `patch:<id>`."""

    id: str
    edits: tuple[JsonEdit, ...]

    @property
    def factor(self) -> str:
        return f"patch:{self.id}"

    @property
    def meds(self) -> frozenset[int]:
        return frozenset(e.med for e in self.edits)


def apply_edits(doc: dict, edits: Iterable[JsonEdit]) -> dict:
    """Return a deep copy of `doc` with `edits` applied in order."""
    out = copy.deepcopy(doc)
    for e in edits:
        node = out
        for step in e.path[:-1]:
            node = node[step]
        node[e.path[-1]] = copy.deepcopy(e.value)
    return out


def validate_response(doc: dict) -> list[str]:
    """Invariants of real responses that an edit must keep (design §C). Returns violations."""
    problems = []
    ids = []
    for i, ent in enumerate(doc.get("Entities") or []):
        ids.append(ent.get("Id"))
        concepts = ent.get("ICD10CMConcepts") or []
        scores = [c.get("Score") for c in concepts]
        if len(concepts) not in (0, 5):
            problems.append(f"entity {i}: {len(concepts)} concepts (expected 0 or 5)")
        if scores != sorted(scores, reverse=True):
            problems.append(f"entity {i}: concept scores not sorted descending")
        if len(scores) > 1 and scores[0] == scores[1]:
            problems.append(f"entity {i}: tie at the top concept")
        for s in [ent.get("Score"), *scores, *(t.get("Score") for t in ent.get("Traits") or [])]:
            if s is not None and not 0.0 <= s <= 1.0:
                problems.append(f"entity {i}: score {s} outside [0, 1]")
    if len(ids) != len(set(ids)):
        problems.append("repeated entity Id")
    return problems


@dataclass(frozen=True, slots=True)
class MedInfo:
    med: int
    status: str
    model_version: str | None
    raw_sha256: str | None


@dataclass(eq=False)
class Evidence:
    """Columnar evidence of a set of medications. Treat as immutable; caches live in `_cache`."""

    meds: tuple[int, ...]
    info: Mapping[int, MedInfo]
    codes: list[str]
    types: list[str]
    # candidate columns (one row per entity x concept, array order)
    c_med: np.ndarray
    c_ent: np.ndarray  # row in the entity columns
    c_rank: np.ndarray  # concept position inside its entity (0 = first listed)
    c_code: np.ndarray  # index into `codes`
    c_cs: np.ndarray  # concept Score
    c_es: np.ndarray  # entity Score
    c_type: np.ndarray  # index into `types`
    # entity columns (one row per entity occurrence, array order, including entities without concepts)
    e_med: np.ndarray
    e_pos: np.ndarray  # position in the Entities array
    e_eid: np.ndarray  # ACM entity Id (position + 1 when absent, like V2's fallback)
    e_traits: list[tuple[tuple[str, float | None], ...]]
    patches: frozenset[Patch] = frozenset()
    _raw: Mapping[int, str | None] = field(default_factory=dict, repr=False)
    _cache: dict = field(default_factory=dict, repr=False)

    @classmethod
    def from_responses(
        cls, responses: Iterable[tuple[int, str | None]], meds: Iterable[int] | None = None
    ) -> Evidence:
        """Build evidence from (id_medication, raw ds_api_response) pairs.

        `meds` lists the medications in scope; those without a response row are STATUS_MISSING.
        """
        raw = dict(responses)
        scope = sorted(set(meds) if meds is not None else raw)
        return cls._build(scope, raw, {}, frozenset())

    @classmethod
    def _build(
        cls,
        scope: list[int],
        raw: Mapping[int, str | None],
        docs: Mapping[int, dict | None],
        patches: frozenset[Patch],
    ) -> Evidence:
        codes: list[str] = []
        code_ix: dict[str, int] = {}
        types: list[str] = []
        type_ix: dict[str, int] = {}
        c_med, c_ent, c_rank, c_code, c_cs, c_es, c_type = [], [], [], [], [], [], []
        e_med, e_pos, e_eid, e_traits = [], [], [], []
        info = {}
        for med in scope:
            text = raw.get(med)
            if med not in raw:
                info[med] = MedInfo(med, STATUS_MISSING, None, None)
                continue
            sha = None if text is None else hashlib.sha256(text.encode("utf-8", "surrogateescape")).hexdigest()
            doc = docs.get(med)
            if doc is None:
                try:
                    doc = json.loads(text)  # type: ignore[arg-type]
                except (TypeError, json.JSONDecodeError):
                    doc = None
            if not isinstance(doc, dict):
                info[med] = MedInfo(med, STATUS_FAILED, None, sha)
                continue
            entities = doc.get("Entities") or []
            info[med] = MedInfo(med, STATUS_OK if entities else STATUS_EMPTY, doc.get("ModelVersion"), sha)
            for pos, ent in enumerate(entities):
                erow = len(e_med)
                eid = ent.get("Id")
                e_med.append(med)
                e_pos.append(pos)
                e_eid.append(pos + 1 if eid is None else eid)
                e_traits.append(tuple((t.get("Name"), t.get("Score")) for t in ent.get("Traits") or [] if t.get("Name")))
                tp = ent.get("Type")
                if tp not in type_ix:
                    type_ix[tp] = len(types)
                    types.append(tp)
                for rank, con in enumerate(ent.get("ICD10CMConcepts") or []):
                    code = con.get("Code")
                    if not code:
                        continue
                    if code not in code_ix:
                        code_ix[code] = len(codes)
                        codes.append(code)
                    c_med.append(med)
                    c_ent.append(erow)
                    c_rank.append(rank)
                    c_code.append(code_ix[code])
                    c_cs.append(con.get("Score"))
                    c_es.append(ent.get("Score"))
                    c_type.append(type_ix[tp])
        return cls(
            meds=tuple(scope),
            info=info,
            codes=codes,
            types=types,
            c_med=np.asarray(c_med, dtype=np.int64),
            c_ent=np.asarray(c_ent, dtype=np.int64),
            c_rank=np.asarray(c_rank, dtype=np.int64),
            c_code=np.asarray(c_code, dtype=np.int64),
            c_cs=np.asarray(c_cs, dtype=np.float64),
            c_es=np.asarray(c_es, dtype=np.float64),
            c_type=np.asarray(c_type, dtype=np.int64),
            e_med=np.asarray(e_med, dtype=np.int64),
            e_pos=np.asarray(e_pos, dtype=np.int64),
            e_eid=np.asarray(e_eid, dtype=np.int64),
            e_traits=e_traits,
            patches=patches,
            _raw=raw,
        )

    def patched(self, patches: Iterable[Patch]) -> Evidence:
        """Evidence with `patches` applied on top of the original responses (cached per patch set)."""
        wanted = frozenset(patches) | self.patches
        if wanted == self.patches:
            return self
        base = self._cache.get("_base", self)
        key = ("patched", wanted)
        if key not in base._cache:
            docs = {}
            for med in sorted({m for p in wanted for m in p.meds}):
                text = base._raw.get(med)
                if text is None:
                    raise ValueError(f"patch on medication {med} without a stored response")
                doc = json.loads(text)
                edits = [e for p in sorted(wanted, key=lambda p: p.id) for e in p.edits if e.med == med]
                docs[med] = apply_edits(doc, edits)
            ev = Evidence._build(list(base.meds), base._raw, docs, wanted)
            ev._cache["_base"] = base
            base._cache[key] = ev
        return base._cache[key]

    def subset(self, meds: Iterable[int]) -> Evidence:
        """Evidence restricted to `meds` (original responses, patches re-applied)."""
        scope = sorted(set(meds))
        missing = [m for m in scope if m not in self.info]
        if missing:
            raise KeyError(f"medications not in evidence: {missing[:5]}")
        base = self._cache.get("_base", self)
        ev = Evidence._build(scope, {m: base._raw[m] for m in scope if m in base._raw}, {}, frozenset())
        return ev.patched(self.patches) if self.patches else ev

    def status(self, med: int) -> str:
        return self.info[med].status

    def model_version(self, med: int) -> str | None:
        return self.info[med].model_version

    def extraction_doc(self, med: int) -> dict | None:
        """Parsed response of `med` with patches applied and without transport metadata (level 2)."""
        text = self._cache.get("_base", self)._raw.get(med)
        if text is None:
            return None
        doc = json.loads(text)
        edits = [e for p in sorted(self.patches, key=lambda p: p.id) for e in p.edits if e.med == med]
        doc = apply_edits(doc, edits) if edits else doc
        doc.pop(TRANSPORT_KEY, None)
        return doc


def load_evidence(snap: str = "v1", meds: Iterable[int] | None = None) -> Evidence:
    """Evidence from a Parquet snapshot of `hd_int_med_disease_api_response`."""
    from habench.data.store import load_table

    tab = load_table(snap, "hd_int_med_disease_api_response", ["id_medication", "ds_api_response"])
    ids = tab.column("id_medication").to_pylist()
    texts = tab.column("ds_api_response").to_pylist()
    wanted = None if meds is None else set(meds)
    pairs = ((i, t) for i, t in zip(ids, texts) if wanted is None or i in wanted)
    return Evidence.from_responses(pairs, meds)
