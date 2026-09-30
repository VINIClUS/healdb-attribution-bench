"""Shared types of scenario generation: Scenario, Candidate, the per-group context and the oracle assessment.

Family and subfamily labels live only in `Scenario` (truth side). Contrast, query and patch ids are opaque
hashes that never contain a family name or the seed value in the clear.
"""

from __future__ import annotations

import dataclasses
import random
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field

from habench.oracle.contrast import Contrast, canonical_json, make_contrast
from habench.oracle.hybrids import Hybrids
from habench.pipeline.catalog import Config
from habench.pipeline.evidence import STATUS_FAILED, STATUS_MISSING, Evidence
from habench.pipeline.mapping import Hierarchy
from habench.scenarios.config import ScenarioConfig
from habench.scenarios.ids import opaque_id, rng_for
from habench.scenarios.queries import QuerySample, sample_queries
from habench.types import AssocKey


@dataclass(frozen=True)
class Scenario:
    contrast: Contrast
    family: str
    subfamily: str
    queries: tuple[tuple[str, AssocKey], ...]
    inclusion: dict[str, float]
    notes: tuple[str, ...] = ()

    def to_json(self) -> dict:
        return {
            "contrast": self.contrast.to_json(),
            "family": self.family,
            "subfamily": self.subfamily,
            "queries": [[qid, [k.med, k.system, k.version, k.code]] for qid, k in self.queries],
            "inclusion": {q: self.inclusion[q] for q in sorted(self.inclusion)},
            "notes": list(self.notes),
        }

    def canonical(self) -> str:
        return canonical_json(self.to_json())


@dataclass(frozen=True)
class Candidate:
    family: str
    subfamily: str
    contrast: Contrast
    notes: tuple[str, ...] = ()


@dataclass
class GenerationReport:
    """Counts of what generation produced, dropped (by family and reason) and excluded as ineligible."""

    produced: Counter = field(default_factory=Counter)  # "family/subfamily" -> scenarios
    dropped: Counter = field(default_factory=Counter)  # "family:reason" -> candidates
    ineligible: Counter = field(default_factory=Counter)  # reason -> queries (or medications)
    errors: list[str] = field(default_factory=list)  # generation errors (SPEC 10.2), by cid

    def drop(self, family: str, reason: str) -> None:
        self.dropped[f"{family}:{reason}"] += 1

    def to_json(self) -> dict:
        return {
            "produced": dict(sorted(self.produced.items())),
            "dropped": dict(sorted(self.dropped.items())),
            "ineligible": dict(sorted(self.ineligible.items())),
            "errors": sorted(self.errors),
        }


@dataclass
class Ctx:
    """One document group being generated: its evidence (built once), parsed responses and the report."""

    partition: str
    seed: int
    group: str
    meds: tuple[int, ...]
    ev: Evidence
    hier: Hierarchy
    cfg: ScenarioConfig
    report: GenerationReport
    docs: dict[int, dict] = field(default_factory=dict)  # parsed responses of the usable medications

    def __post_init__(self) -> None:
        self.docs = {m: self.ev.extraction_doc(m) for m in self.meds
                     if self.ev.status(m) not in (STATUS_FAILED, STATUS_MISSING)}

    def rng(self, *label: object) -> random.Random:
        return rng_for(self.seed, self.group, *label)

    def contrast(self, x0: Config, x1: Config, *, space: str = "who", **kw) -> Contrast:
        """make_contrast with the sealed check on, and an opaque cid hashed from the contrast content."""
        if "patches" in kw:
            kw["patches"] = sorted(kw["patches"], key=lambda p: p.id)  # the order Contrast.to_json uses
        draft = make_contrast("", self.group, self.meds, space, x0, x1, **kw)
        return dataclasses.replace(draft, cid=opaque_id("c", self.seed, draft.canonical()))

    def candidate(self, family: str, subfamily: str, x0: Config, x1: Config, *, notes: tuple[str, ...] = (),
                  **kw) -> Candidate | None:
        """A candidate, or None (drop recorded) if the contrast is invalid. SealedError is never swallowed."""
        try:
            return Candidate(family, subfamily, self.contrast(x0, x1, **kw), notes)
        except ValueError:
            self.report.drop(family, "invalid_contrast")
            return None


@dataclass(frozen=True)
class Assessed:
    scenario: Scenario
    hybrids: Hybrids
    sample: QuerySample


def assess(ctx: Ctx, cand: Candidate, *, null: bool = False) -> Assessed | None:
    """Run the oracle endpoints of a candidate and sample its queries; None (with a recorded reason) if dropped.

    Non-null families need at least one changed query. A null contrast (family N) must have none among *all*
    candidate keys: any changed query drops it and counts as a generation error (SPEC 10.2).
    """
    c = cand.contrast
    h = Hybrids(c, ctx.ev, ctx.hier)
    if not h.endpoints_reproduce():
        ctx.report.drop(cand.family, "endpoints_not_reproduced")
        ctx.report.errors.append(c.cid)
        return None
    s = sample_queries(h, seed=ctx.seed, cid=c.cid, null=null)
    ctx.report.ineligible.update(s.ineligible)
    if null and s.n_changed:
        ctx.report.drop(cand.family, "null_contrast_has_changed_query")
        ctx.report.errors.append(c.cid)
        return None
    if not null and not s.n_changed:
        ctx.report.drop(cand.family, "no_changed_query")
        return None
    if not s.queries:
        ctx.report.drop(cand.family, "no_queries")
        return None
    notes = (*cand.notes, f"population: {s.n_changed} changed, {s.n_unchanged} unchanged")
    sc = Scenario(c, cand.family, cand.subfamily, s.queries, s.inclusion, notes)
    return Assessed(sc, h, s)


def take(ctx: Ctx, candidates: Iterable[Candidate], n: int, *, null: bool = False,
         accept=None) -> list[Assessed]:
    """Assess candidates in order until `n` are accepted. `accept(assessed) -> bool` adds a family rule."""
    out: list[Assessed] = []
    seen: set[str] = set()
    for cand in candidates:
        if len(out) >= n:
            break
        if cand.contrast.cid in seen:
            ctx.report.drop(cand.family, "duplicate_candidate")
            continue
        seen.add(cand.contrast.cid)
        a = assess(ctx, cand, null=null)
        if a is None:
            continue
        if accept is not None and not accept(a):
            continue
        out.append(a)
    return out
