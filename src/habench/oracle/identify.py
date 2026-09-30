"""Identification reference over a declared set of histories (SPEC §8).

A history (8.1) is the group's evidence with a's candidates as hypothesized, the executed levels of x0/x1
and the variants κ0/κ1. The declared configs and the rest of the group are fixed by the context.

`identify` takes the true history h*, the universe U (histories, e.g. from `oracle.universe`), a cell and
returns `W_lo`, `W_hi` and the state (8.3):
- W_hi: families of U ∪ {h*} whose **marginal** observation of `a` equals h*'s;
- W_lo: {F*} plus the families of the W_hi histories whose witness, lifted to the true group
  (`lift(h)`; identity for histories that already are whole groups), leaves the whole visible group
  observation equal to h*'s;
- saturated: passed by the caller (the expansion saturated and class(h*) ∈ U).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Hashable, Iterable, Mapping
from dataclasses import dataclass, field

from habench.oracle.contrast import Contrast, make_contrast
from habench.oracle.families import analyze
from habench.oracle.hybrids import Hybrids, all_subsets
from habench.oracle.truth import CellSpec, Identification, split_view
from habench.pipeline import catalog, mapping
from habench.pipeline.catalog import Config
from habench.pipeline.evidence import Evidence
from habench.pipeline.mapping import Hierarchy
from habench.types import AssocKey, Family

FAILED_STAGE = {
    "map": "map", "icd_thr": "icd_thr", "ent_thr": "ent_thr",
    "trait_veto": "trait", "trait_hyp": "trait", "trait_required": "trait", "trait_type": "trait",
}


@dataclass(frozen=True)
class Context:
    """What every history of one query shares: hierarchy, space, declared configs, bundles, group meds."""

    hier: Hierarchy
    space: str
    d0: Config
    d1: Config
    meds: tuple[int, ...]
    bundles: Mapping[str, tuple[str, ...]] = field(default_factory=dict)


@dataclass(eq=False)
class History:
    evidence: Evidence
    x0: Config
    x1: Config
    variants0: frozenset[str] = frozenset()
    variants1: frozenset[str] = frozenset()
    label: str = ""
    _cache: dict = field(default_factory=dict, repr=False)

    def contrast(self, ctx: Context) -> Contrast:
        if "contrast" not in self._cache:
            self._cache["contrast"] = make_contrast(
                self.label or "h", "u", ctx.meds, ctx.space, self.x0, self.x1, d0=ctx.d0, d1=ctx.d1,
                variants0=self.variants0, variants1=self.variants1,
                bundles={b: c for b, c in ctx.bundles.items() if set(c) & self.x0.diff(self.x1)},
                check_sealed=False,
            )
        return self._cache["contrast"]

    def hybrids(self, ctx: Context, levels: str = "executed") -> Hybrids:
        k = ("hybrids", levels)
        if k not in self._cache:
            self._cache[k] = Hybrids(self.contrast(ctx), self.evidence, ctx.hier, levels=levels)
        return self._cache[k]

    def family(self, ctx: Context, key: AssocKey) -> Family | None:
        k = ("family", key)
        if k not in self._cache:
            h = self.hybrids(ctx)
            self._cache[k] = analyze(h.D, h.truth_table(key)).family
        return self._cache[k]


# ---------------------------------------------------------------------- observation (SPEC 8.1 table)


def _keys_of(h: Hybrids, key: AssocKey | None) -> Callable[[AssocKey], bool]:
    return (lambda k: True) if key is None else (lambda k: k == key)


def _target(hier: Hierarchy, level: str, space, code: str) -> str | None:
    """Key code of `code` under a map level in the space, ignoring the gate (as core._code_map)."""
    if space.kind == "cm":
        return code
    return mapping.who_map(hier, code, catalog.MAP_LEVELS[level][2])[0]


def _trace_summary(h: Hybrids, S: frozenset[str], key: AssocKey | None, winners_only: bool) -> tuple:
    """Per record (of `key`, or all records when key is None): (code, verdict, failed stages)."""
    res = h.run(S, trace=True)
    tr = res.trace
    levels = {str(h.config(frozenset())["map"]), str(h.config(frozenset(h.D))["map"])}
    failed: dict[int, set[str]] = {}
    for d in tr.decisions:
        if not d.verdict:
            failed.setdefault(d.ref, set()).add(FAILED_STAGE[d.stage])
    out = []
    for r in tr.records:
        if key is not None:
            if r.med != key.med or not any(_target(h.hier, lv, h.space, r.code) == key.code for lv in levels):
                continue
        f = frozenset(failed.get(r.rid, ()))
        if winners_only and f:
            continue
        out.append((r.med, r.code, "fail" if f else "pass", tuple(sorted(f))))
    return tuple(out)


def _response_view(ev: Evidence, meds: Iterable[int], top1_only: bool) -> str:
    docs = {}
    for m in meds:
        doc = ev.extraction_doc(m)
        if doc is not None and top1_only:
            doc = dict(doc)
            doc["Entities"] = [
                {**e, "ICD10CMConcepts": (e.get("ICD10CMConcepts") or [])[:1]} for e in doc.get("Entities") or []
            ]
        docs[m] = doc
    return json.dumps(docs, sort_keys=True)


def observation(hist: History, ctx: Context, cell: CellSpec, key: AssocKey, *, marginal: bool = True) -> tuple:
    """o_{v,r}(h): marginal in `a` (8.3 W_hi) or of the whole visible group (8.3 W_lo)."""
    base, abl = split_view(cell.view)
    h = hist.hybrids(ctx)
    D = frozenset(h.D)
    wanted = _keys_of(h, key if marginal else None)
    r0, r1 = h.run(frozenset()), h.run(D)
    if marginal:
        finals = (r0.state(key).value, r1.state(key).value)
    else:
        finals = (tuple(sorted(k for k in r0.present if wanted(k))), tuple(sorted(k for k in r1.present if wanted(k))),
                  tuple(sorted(r0.status.items())))
    obs: list[Hashable] = [("finals", finals)]
    if base != "N1" and base != "N2":
        obs.append(("hashes", not any(f.startswith("patch:") for f in D)))
    if cell.evidence:
        meds = [key.med] if marginal else list(ctx.meds)
        obs.append(("evidence", _response_view(hist.evidence, meds, top1_only="A2" in abl)))
    if cell.code_link:
        obs.append(("levels", hist.x0.items, hist.x1.items))
    if base in ("L2-M", "L3-M"):
        winners = "A6" in abl
        k = key if marginal else None
        obs.append(("trace", _trace_summary(h, frozenset(), k, winners), _trace_summary(h, D, k, winners)))
    if cell.runs_hybrids:
        hb = h if cell.code_link else hist.hybrids(ctx, "declared")
        prep = set(hb.contrast.prep_factors)
        rows = []
        for S in all_subsets(hb.D):
            if not hb.admissible(S) or (cell.no_prep and S & prep):
                continue
            r = hb.run(S)
            rows.append((tuple(sorted(S)), r.state(key).value if marginal else
                         tuple(sorted(k for k in r.present if wanted(k)))))
        obs.append(("replay", tuple(rows)))
    return tuple(obs)


# ---------------------------------------------------------------------- W_lo, W_hi, state


def identify(
    true: History,
    universe: Iterable[History],
    ctx: Context,
    cell: CellSpec,
    key: AssocKey,
    *,
    saturated: bool,
    lift: Callable[[History], History | None] | None = None,
) -> Identification:
    target = observation(true, ctx, cell, key)
    F_star = true.family(ctx, key)
    if F_star is None:
        raise ValueError("identification is defined for changed associations only")
    group_target = observation(true, ctx, cell, key, marginal=False)
    W_hi: set[Family] = {F_star}
    W_lo: set[Family] = {F_star}
    for h in universe:
        if observation(h, ctx, cell, key) != target:
            continue
        F = h.family(ctx, key)
        if F is None:
            continue  # unchanged histories differ in the finals; kept for safety
        W_hi.add(F)
        if F in W_lo:
            continue
        lifted = h if lift is None else lift(h)
        if lifted is not None and observation(lifted, ctx, cell, key, marginal=False) == group_target:
            W_lo.add(F)
    return Identification(frozenset(W_lo), frozenset(W_hi), saturated)
