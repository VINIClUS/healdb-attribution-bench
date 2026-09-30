"""Query sampling per contrast (SPEC 12): <= 25 changed and <= 25 unchanged, seeded, with inclusion probabilities.

Candidate keys (documented choice): every candidate of the group's evidence is projected under each `map` level
realized by h_∅ and h_D, keeping the keys whose code passes the gate of at least one of those levels. This
covers present/present and absent/absent keys (an absent/absent key is one that thresholds or trait rules
filter out in both runs), and it contains every key present in any hybrid, because no patch changes a code.
Changed / unchanged is decided by the oracle: presence in h_∅ against h_D on the contrast space.

Ratio: unchanged sampled = min(#unchanged, max(#changed sampled, 1), cap); family N (`null=True`) has no
changed queries and takes up to the cap. Ineligible (UNAVAILABLE) keys are excluded and counted by reason.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from habench.oracle.hybrids import Hybrids
from habench.pipeline import core
from habench.pipeline.evidence import STATUS_FAILED, STATUS_MISSING
from habench.scenarios.ids import opaque_id, rng_for
from habench.types import AssocKey, Presence

MAX_CHANGED = 25
MAX_UNCHANGED = 25


@dataclass(frozen=True)
class QuerySample:
    queries: tuple[tuple[str, AssocKey], ...]
    inclusion: dict[str, float]
    changed: tuple[AssocKey, ...]  # the whole changed stratum
    n_unchanged: int
    n_changed_sampled: int
    n_unchanged_sampled: int
    ineligible: dict[str, int] = field(default_factory=dict)

    @property
    def n_changed(self) -> int:
        return len(self.changed)


def qid_of(cid: str, key: AssocKey) -> str:
    return opaque_id("q", cid, key.med, key.system, key.version, key.code, n=10)


def candidate_keys(h: Hybrids) -> list[AssocKey]:
    """Sorted candidate keys of the group (see the module docstring)."""
    ev, hier, space = h.evidence, h.hier, h.space
    levels = sorted({str(h.config(frozenset())["map"]), str(h.config(frozenset(h.D))["map"])})
    rec = core.records(ev, "all", "last_upsert")
    keys: set[AssocKey] = set(h.run(frozenset()).present) | set(h.run(frozenset(h.D)).present)
    for lv in levels:
        ok, _ = core._code_map(ev, hier, lv, space)
        kidx, objs = core._keys(ev, hier, rec, lv, space)
        for i in range(len(rec)):
            if kidx[i] >= 0 and ok[rec.code[i]]:
                keys.add(objs[kidx[i]])
    return sorted(keys)


def sample_queries(
    h: Hybrids,
    *,
    seed: int,
    cid: str,
    null: bool = False,
    max_changed: int = MAX_CHANGED,
    max_unchanged: int = MAX_UNCHANGED,
) -> QuerySample:
    ev = h.evidence
    ineligible: Counter[str] = Counter()
    for m in ev.meds:
        if ev.status(m) in (STATUS_FAILED, STATUS_MISSING):
            ineligible[f"unavailable_med:{ev.status(m)}"] += 1
    r0, rD = h.run(frozenset()), h.run(frozenset(h.D))
    changed: list[AssocKey] = []
    unchanged: list[AssocKey] = []
    for key in candidate_keys(h):
        s0, sD = r0.state(key), rD.state(key)
        if Presence.UNAVAILABLE in (s0, sD):
            ineligible[f"unavailable_key:{ev.status(key.med)}"] += 1
            continue
        (changed if s0 != sD else unchanged).append(key)
    rng = rng_for(seed, cid, "queries")
    k_c = 0 if null else min(len(changed), max_changed)
    picked_c = sorted(rng.sample(changed, k_c)) if k_c else []
    k_u = min(len(unchanged), max_unchanged if null else min(max(k_c, 1), max_unchanged))
    picked_u = sorted(rng.sample(unchanged, k_u)) if k_u else []
    inclusion: dict[str, float] = {}
    queries = []
    for picked, n in ((picked_c, len(changed)), (picked_u, len(unchanged))):
        for key in picked:
            qid = qid_of(cid, key)
            inclusion[qid] = len(picked) / n
            queries.append((qid, key))
    return QuerySample(
        queries=tuple(sorted(queries, key=lambda q: q[1])),
        inclusion=inclusion,
        changed=tuple(changed),
        n_unchanged=len(unchanged),
        n_changed_sampled=len(picked_c),
        n_unchanged_sampled=len(picked_u),
        ineligible=dict(ineligible),
    )
