"""Identification of one query in one cell, choosing the universe per SPEC 8.2-8.4 (β3).

- Cells with the full response (L2-*, L3-*, N1, N2, and ablations other than A2): the evidence of `a` is
  observed, so U = the true evidence × the level/variant hypotheses (with the code link only variants
  deviate). There is no expansion; U is saturated and contains h*.
- Cells without the full response (L1 and top-1-only views A2/C2/C4): U = symbolic bundles × hypotheses,
  expanded by `oracle.universe` and memoized per (declared configs, space, key code, observation mode);
  W_lo by lifting each witness into the real group.

Not covered yet (raise `NotImplementedError`; `truth.build_truth` leaves the cell out of the truth):
without the full response, contrasts with patches, bundles or prep factors, declared replay (no code link
with R-A/R-B) and the trace component (L2-M with A2).
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
    l1_observation,
    top1_observer,
    top1_view,
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

    def get(self, c: Contrast, hier: Hierarchy, key_code: str, mode: Mode) -> Expansion:
        th = true_hypothesis(c)
        k = (c.d0.items, c.d1.items, c.space, key_code, th, self.L, self.max_dev, mode)
        if k not in self.store:
            t = time.perf_counter()
            truth = (th.x0, th.x1, th.variants0, th.variants1)
            hyps = hypotheses(c.d0, c.d1, code_link=mode.code_link, max_dev=self.max_dev, true=truth)
            if not any(_same(h, th) for h in hyps):
                hyps.append(th)
            alpha = alphabet(hyps, hier, c.space, key_code)
            ev = BatchEval(hier, c.space, key_code)
            res = expand(hyps, alpha, ev, L=self.L, time_budget=self.time_budget, max_bundles=self.max_bundles,
                         reps_per_class=self.reps_per_class, frontier_by="declared",
                         observe=mode.observer(hier, c.space, key_code, alpha))
            fams = {}
            for cls in res.classes:
                D, tab, _ = cls
                r = analyze(D, dict(zip(all_subsets(D), tab)))
                fams[cls] = r.family if r.changed else None
            sec = time.perf_counter() - t
            self.store[k] = Expansion(hyps, alpha, res, fams, sec)
            self.stats.append({"key_code": key_code, "mode": mode.name, "hypotheses": len(hyps),
                               "alphabet": alpha.size(),
                               "levels": res.levels, "saturated": res.saturated, "cut": res.cut,
                               "core_runs": ev.runs, "seconds": round(sec, 2)})
        return self.store[k]


@dataclass(frozen=True)
class Mode:
    """How the expansion observes a bundle: `l1` (finals) or `top1` (finals + top-1 view), plus the executed
    tables when the cell replays the executed levels (R-A/R-B with the code link)."""

    name: str
    code_link: bool
    replay: bool

    def observer(self, hier, space, key_code, alpha):
        top1 = top1_observer(hier, space, key_code, alpha) if self.name == "top1" else None

        def observe(b, D, tab):
            base = top1(b, D, tab) if top1 else l1_observation(b, D, tab)
            return base + ((D, tab),) if self.replay else base

        return observe


def _mode(cell: CellSpec) -> Mode:
    return Mode("top1" if cell.evidence else "l1", cell.code_link, cell.runs_hybrids)


def _unsupported(c: Contrast, cell: CellSpec) -> str:
    base, abl = split_view(cell.view)
    if cell.full_response:
        return ""
    if any(f.startswith("patch:") for f in c.D):
        return "histories of patched contrasts without the full response are not defined by SPEC §8"
    if c.bundles or c.prep_factors:
        return "the expansion over bundles or prep factors is not implemented"
    if cell.runs_hybrids and not cell.code_link:
        return "declared replay over expanded bundles is not implemented"
    if base in ("L2-M", "L3-M") and cell.evidence:
        return "trace observation over expanded bundles is not implemented"
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
    if cell.full_response:
        th = true_hypothesis(c)
        hyps = hypotheses(c.d0, c.d1, code_link=cell.code_link, true=(th.x0, th.x1, th.variants0, th.variants1))
        universe = [
            History(group_ev, h.x0.with_items({p.factor: False for p in c.patches}),
                    h.x1.with_items({p.factor: True for p in c.patches}), h.variants0, h.variants1,
                    label=f"h{i}", runs=runs)
            for i, h in enumerate(hyps)
        ]
        return identify(true, universe, ctx, cell, q.key, saturated=True)
    return _identify_expanded(c, group_ev, hier, q, cell, ctx, true, cache)


def _true_observation(c: Contrast, hier: Hierarchy, q: QueryTruth, doc: dict | None, exp: Expansion,
                      mode: Mode) -> tuple:
    obs: tuple = (q.x0.value, q.x1.value)
    if mode.name == "top1":
        obs += (top1_view((doc or {}).get("Entities") or [], hier, c.space, q.key.code, exp.alpha),)
    if mode.replay:
        D = tuple(sorted(c.D))
        obs += ((D, tuple(q.table[S].value for S in all_subsets(D))),)
    return obs


def _identify_expanded(c, group_ev, hier, q, cell, ctx, true, cache: UniverseCache) -> Identification:
    mode = _mode(cell)
    exp = cache.get(c, hier, q.key.code, mode)
    F_star = q.family
    doc = group_ev.extraction_doc(q.key.med)
    obs = _true_observation(c, hier, q, doc, exp, mode)
    W_hi: set[Family] = {F_star}
    witnesses: dict[Family, list[tuple]] = {}
    for cls, F in exp.families.items():
        if F is None or cls[2] != obs:
            continue
        W_hi.add(F)
        witnesses.setdefault(F, []).append(cls)
    W_lo: set[Family] = {F_star}
    # outside a's candidates the lifted group equals the true one, so the evidence component is not compared
    group_target = _without_evidence(observation(true, ctx, cell, q.key, marginal=False))
    for F, classes in witnesses.items():
        if F in W_lo:
            continue
        for cls in classes[: cache.lift_attempts]:
            b, h = exp.result.classes[cls]
            lifted = _lifted_evidence(group_ev, c, q.key.med, lift_doc(doc, b, hier, c.space, q.key.code, exp.alpha))
            hist = History(lifted, h.x0, h.x1, h.variants0, h.variants1, label="lift")
            if _without_evidence(observation(hist, ctx, cell, q.key, marginal=False)) == group_target:
                W_lo.add(F)
                break
    saturated = exp.result.saturated and _true_in_u(c, hier, q, doc, exp, obs)
    return Identification(frozenset(W_lo), frozenset(W_hi), saturated,
                          note="" if saturated else (exp.result.cut or "class(h*) not in U"))


def _without_evidence(obs: tuple) -> tuple:
    return tuple(o for o in obs if o[0] != "evidence")


def _true_in_u(c: Contrast, hier: Hierarchy, q: QueryTruth, doc: dict | None, exp: Expansion, obs: tuple) -> bool:
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
    return (D, tab, obs) in exp.result.classes


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
