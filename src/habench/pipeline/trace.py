"""Per-stage trace of one run: candidates, records, per-filter decisions with reasons (L2-M material)."""

from __future__ import annotations

from dataclasses import dataclass

from habench.types import AssocKey


@dataclass(frozen=True, slots=True)
class CandRow:
    cid: int  # candidate index in the evidence
    med: int
    pos: int  # entity position in the response array
    eid: int  # ACM entity Id
    code: str
    rank: int  # concept position inside the entity
    es: float
    cs: float
    tp: str
    traits: tuple[tuple[str, float | None], ...]
    selected: bool  # kept by `sel`


@dataclass(frozen=True, slots=True)
class RecordRow:
    rid: int
    med: int
    code: str
    eid: int | None  # None for code-keyed records (upsert rules)
    members: tuple[int, ...]  # candidate ids, in order
    source: int  # candidate id that set the scalars
    es: float
    cs: float
    tp: str
    traits: tuple[tuple[str, float | None], ...]  # union, collation order of names
    key: AssocKey | None  # projection in the run's key space (None: unmapped)


@dataclass(frozen=True, slots=True)
class Decision:
    ref: int  # rid
    stage: str  # map | trait_veto | trait_hyp | icd_thr | ent_thr | trait_required | trait_type
    verdict: bool  # True = passes
    reason: str


@dataclass(frozen=True, slots=True)
class Trace:
    meds: tuple[int, ...]
    candidates: tuple[CandRow, ...]
    records: tuple[RecordRow, ...]
    decisions: tuple[Decision, ...]

    def discards(self) -> tuple[Decision, ...]:
        return tuple(d for d in self.decisions if not d.verdict)
