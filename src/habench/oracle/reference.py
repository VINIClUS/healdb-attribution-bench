"""Identification of one query in one cell, choosing the universe per SPEC 8.2-8.4 (β3).

- Cells with the full response (L2-*, L3-*, N1, N2, and ablations other than A2): the evidence of `a` is
  observed, so U = the true evidence × the level/variant hypotheses (with the code link only variants
  deviate). There is no expansion; U is saturated and contains h*.
- L1 (R-C): U = symbolic bundles × hypotheses, expanded by `oracle.universe` and memoized per
  (declared configs, space, key code); W_lo by lifting each witness into the real group.

Not covered yet (raise `NotImplementedError`, and the caller leaves the cell out of the truth):
top-1-only views (A2, C2, C4), contrasts with patches, bundles or prep factors under L1.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from habench.oracle.contrast import Contrast
from habench.oracle.families import analyze
from habench.oracle.hybrids import all_subsets
from habench.oracle.identify import Context, History, identify, observation
from habench.oracle.truth import CellSpec, Identification, QueryTruth, split_view
from habench.oracle.universe import (
    L_MAX,
    BatchEval,
    ExpansionResult,
    Hypothesis,
    alphabet,
    expand,
    hypotheses,
    lift_doc,
    symbolize,
)
from habench.pipeline.catalog import Config
from habench.pipeline.evidence import Evidence
from habench.pipeline.mapping import Hierarchy
from habench.types import Family


def _levels(x: Config) -> Config:
    return Config.of({f: v for f, v in x.items if not f.startswith("patch:")})


def true_hypothesis(c: Contrast) -> Hypothesis:
    return Hypothesis(_levels(c.x0), _levels(c.x1), c.variants0, c.variants1, ())


def _same(h: Hypothesis, t: Hypothesis) -> bool:
    return (h.x0, h.x1, h.variants0, h.variants1) == (t.x0, t.x1, t.variants0, t.variants1)


@dataclass
class Expansion:
    hyps: list[Hypothesis]
    alpha: object
    result: ExpansionResult
    families: dict[tuple, Family | None]
    seconds: float


@dataclass
class UniverseCache:
    """Memo of L1 expansions and the A15 measurements."""

    L: int = L_MAX
    max_dev: int = 3
    time_budget: float = 120.0
    max_bundles: int = 50_000
    reps_per_class: int = 1
    lift_attempts: int = 5
    store: dict = field(default_factory=dict)
    stats: list[dict] = field(default_factory=list)

    def get(self, c: Contrast, hier: Hierarchy, key_code: str) -> Expansion:
        k = (c.d0.items, c.d1.items, c.space, key_code, true_hypothesis(c), self.L, self.max_dev)
        if k not in self.store:
            t = time.perf_counter()
            hyps = hypotheses(c.d0, c.d1, code_link=False, max_dev=self.max_dev)
            th = true_hypothesis(c)
            if not any(_same(h, th) for h in hyps):
                hyps.append(th)
            alpha = alphabet(hyps, hier, c.space, key_code)
            ev = BatchEval(hier, c.space, key_code)
            res = expand(hyps, alpha, ev, L=self.L, time_budget=self.time_budget, max_bundles=self.max_bundles,
                         reps_per_class=self.reps_per_class, frontier_by="declared")
            fams = {}
            for cls in res.classes:
                D, tab, _ = cls
                r = analyze(D, dict(zip(all_subsets(D), tab)))
                fams[cls] = r.family if r.changed else None
            sec = time.perf_counter() - t
            self.store[k] = Expansion(hyps, alpha, res, fams, sec)
            self.stats.append({"key_code": key_code, "hypotheses": len(hyps), "alphabet": alpha.size(),
                               "levels": res.levels, "saturated": res.saturated, "cut": res.cut,
                               "core_runs": ev.runs, "seconds": round(sec, 2)})
        return self.store[k]


def _unsupported(c: Contrast, cell: CellSpec) -> str:
    base, abl = split_view(cell.view)
    if cell.evidence and not cell.full_response:
        return "top-1-only views (A2) are not covered by the universe yet"
    if not cell.evidence:
        if any(f.startswith("patch:") for f in c.D):
            return "L1 histories for patched contrasts are not defined by SPEC §8"
        if c.bundles or c.prep_factors:
            return "L1 expansion over bundles or prep factors is not implemented"
    return ""


def identify_query(
    c: Contrast,
    group_ev: Evidence,
    hier: Hierarchy,
    q: QueryTruth,
    cell: CellSpec,
    *,
    cache: UniverseCache,
    runs: dict | None = None,
) -> Identification:
    why = _unsupported(c, cell)
    if why:
        raise NotImplementedError(why)
    ctx = Context(hier, c.space, c.d0, c.d1, c.meds, c.bundle_map)
    runs = {} if runs is None else runs
    true = History(group_ev, c.x0, c.x1, c.variants0, c.variants1, label="true", runs=runs)
    if cell.evidence:
        th = true_hypothesis(c)
        hyps = hypotheses(c.d0, c.d1, code_link=cell.code_link, true=(th.x0, th.x1, th.variants0, th.variants1))
        universe = [
            History(group_ev, h.x0.with_items({p.factor: False for p in c.patches}),
                    h.x1.with_items({p.factor: True for p in c.patches}), h.variants0, h.variants1,
                    label=f"h{i}", runs=runs)
            for i, h in enumerate(hyps)
        ]
        return identify(true, universe, ctx, cell, q.key, saturated=True)
    return _identify_l1(c, group_ev, hier, q, cell, ctx, true, cache, runs)


def _identify_l1(c, group_ev, hier, q, cell, ctx, true, cache: UniverseCache, runs) -> Identification:
    exp = cache.get(c, hier, q.key.code)
    F_star = q.family
    obs = (q.x0.value, q.x1.value)
    W_hi: set[Family] = {F_star}
    witnesses: dict[Family, list[tuple]] = {}
    for cls, F in exp.families.items():
        if F is None or cls[2] != obs:
            continue
        W_hi.add(F)
        witnesses.setdefault(F, []).append(cls)
    W_lo: set[Family] = {F_star}
    doc = group_ev.extraction_doc(q.key.med)
    group_target = observation(true, ctx, cell, q.key, marginal=False)
    for F, classes in witnesses.items():
        if F in W_lo:
            continue
        for cls in classes[: cache.lift_attempts]:
            b, h = exp.result.classes[cls]
            lifted = _lifted_evidence(group_ev, c, q.key.med, lift_doc(doc, b, hier, c.space, q.key.code, exp.alpha))
            hist = History(lifted, h.x0, h.x1, h.variants0, h.variants1, label="lift")
            if observation(hist, ctx, cell, q.key, marginal=False) == group_target:
                W_lo.add(F)
                break
    saturated = exp.result.saturated and _true_in_u(c, hier, q, doc, exp)
    return Identification(frozenset(W_lo), frozenset(W_hi), saturated,
                          note="" if saturated else (exp.result.cut or "class(h*) not in U"))


def _true_in_u(c: Contrast, hier: Hierarchy, q: QueryTruth, doc: dict | None, exp: Expansion) -> bool:
    """class(h*) ∈ U: a's true candidates symbolize, reproduce h*'s class, and that class is in U."""
    if doc is None:
        return False
    b = symbolize(doc, hier, c.space, q.key.code, exp.alpha)
    if b is None:
        return False
    th = true_hypothesis(c)
    (D, tab), = BatchEval(hier, c.space, q.key.code).tables([b], th)
    truth = {S: st.value for S, st in q.table.items()}
    if dict(zip(all_subsets(D), tab)) != truth:
        return False
    return (D, tab, (tab[0], tab[-1])) in exp.result.classes


def _lifted_evidence(group_ev: Evidence, c: Contrast, med: int, doc: dict) -> Evidence:
    rows = []
    for m in c.meds:
        if m == med:
            rows.append((m, json.dumps(doc)))
            continue
        d = group_ev.extraction_doc(m)
        if d is not None:
            rows.append((m, json.dumps(d)))
        elif group_ev.status(m) == "failed":
            rows.append((m, None))
    return Evidence.from_responses(rows, meds=c.meds)


IdentFactory = Callable[[QueryTruth, CellSpec], Identification]


def ident_fn(c: Contrast, group_ev: Evidence, hier: Hierarchy, cache: UniverseCache) -> IdentFactory:
    """An `ident` callback for `truth.build_truth`; uncovered cells raise NotImplementedError and stay out."""
    runs: dict = {}

    def f(q: QueryTruth, cell: CellSpec) -> Identification:
        return identify_query(c, group_ev, hier, q, cell, cache=cache, runs=runs)

    return f
