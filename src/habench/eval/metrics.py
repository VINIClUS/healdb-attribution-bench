"""Metrics of SPEC §10 over scored queries, always stratifiable by origin and scenario family.

One `QueryRecord` per (execution, query), where an execution is method × view × capability × budget ×
contrast (× repetition). Ratio estimators are aggregated per query; inference by group is in `eval.stats`.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from habench.types import CATEGORICAL, Family, OutputState

CHANGED_CELLS = ("identificado", "ambiguo")
BAD = ("errado", "indevidamente_exclusivo")
CATEGORICAL_STATES = frozenset(s.value for s in CATEGORICAL)
ATTRIBUTIONS = frozenset({OutputState.EXPLICACAO_VERIFICADA.value, OutputState.ALTERNATIVAS.value})


@dataclass(frozen=True)
class QueryRecord:
    method: str
    view: str
    capability: str
    budget: int
    contrast: str
    group: str
    scenario_family: str
    origin: str
    qid: str
    cell: str
    state: str
    outcome: str
    reason: str = ""
    families: tuple[Family, ...] = ()
    F_star: Family | None = None
    repetition: int = 0


@dataclass(frozen=True)
class Cost:
    """Raw cost of one execution on one contrast (SPEC 10.3 "Custo")."""

    method: str
    view: str
    capability: str
    budget: int
    contrast: str
    n_queries: int
    evaluations: int = 0
    bytes_read: int = 0
    cpu_seconds: float = 0.0
    peak_rss: int = 0
    extra: Mapping[str, float] = field(default_factory=dict)


def _ratio(num: float, den: float) -> float:
    return num / den if den else 0.0


def query_sets(records: Sequence[QueryRecord]) -> dict[str, list[QueryRecord]]:
    """SPEC 10.1."""
    return {
        "Q_c": [r for r in records if r.cell in CHANGED_CELLS],
        "Q_inc": [r for r in records if r.cell == "incompleta"],
        "Q_ind": [r for r in records if r.cell == "indeterminado"],
        "Q_u": [r for r in records if r.cell == "inalterado"],
    }


def primary(records: Sequence[QueryRecord]) -> dict[str, float]:
    """SPEC 10.2: coverage, raw coverage, literal and committed selective risk, null control."""
    qs = query_sets(records)
    q_c, q_u = qs["Q_c"], qs["Q_u"]
    cat = [r for r in q_c + qs["Q_inc"] if r.state in CATEGORICAL_STATES]
    bad = [r for r in cat if r.outcome in BAD]
    committed = [r for r in cat if r.outcome != "nao_comprometido"]
    null = [r for r in records if r.scenario_family == "N"]
    false_null = [r for r in null if r.cell == "inalterado" and r.state in ATTRIBUTIONS]
    return {
        "cobertura": _ratio(sum(r.outcome == "correto_sustentado" for r in q_c), len(q_c)),
        "cobertura_bruta": _ratio(sum(r.state in CATEGORICAL_STATES for r in q_c), len(q_c)),
        "risco_seletivo": _ratio(len(bad), len(cat)),
        "risco_comprometido": _ratio(len(bad), len(committed)),
        "null_group_rate": _ratio(len({r.group for r in false_null}), len({r.group for r in null})),
        "null_false_attributions_per_contrast": _ratio(len(false_null), len({r.contrast for r in null})),
        "falha_rate": _ratio(sum(r.outcome == "falha" for r in q_c), len(q_c)),
        "n_indeterminado": len(qs["Q_ind"]),
        "n_incompleta": len(qs["Q_inc"]),
        "n_changed": len(q_c),
    }


def cause_class(f: str) -> str:
    return "evidence" if f.startswith("patch:") else f


def _union(F: Family | None) -> set[str]:
    return {cause_class(f) for S in (F or ()) for f in S}


def per_class_prf(records: Sequence[QueryRecord]) -> dict[str, dict[str, float]]:
    """Precision, recall and F1 per cause class over Q_c with a complete oracle (auxiliary, §11.2)."""
    tp: Counter = Counter()
    fp: Counter = Counter()
    fn: Counter = Counter()
    for r in records:
        if r.cell not in CHANGED_CELLS or r.F_star is None:
            continue
        pred = _union(r.families[0]) if r.state == OutputState.EXPLICACAO_VERIFICADA.value and r.families else set()
        true = _union(r.F_star)
        for c in pred & true:
            tp[c] += 1
        for c in pred - true:
            fp[c] += 1
        for c in true - pred:
            fn[c] += 1
    out = {}
    for c in sorted(set(tp) | set(fp) | set(fn)):
        p = _ratio(tp[c], tp[c] + fp[c])
        rc = _ratio(tp[c], tp[c] + fn[c])
        out[c] = {"precision": p, "recall": rc, "f1": _ratio(2 * p * rc, p + rc)}
    return out


def set_metrics(records: Sequence[QueryRecord]) -> dict[str, float]:
    """Exact family, precision |F ∩ F*|/|F| and recall |F ∩ F*|/|F*|, sets as elements (V outputs only)."""
    rows = [r for r in records if r.cell in CHANGED_CELLS and r.F_star is not None
            and r.state == OutputState.EXPLICACAO_VERIFICADA.value and r.families]
    if not rows:
        return {"n": 0, "exact": 0.0, "precision": 0.0, "recall": 0.0}
    exact = sum(r.families[0] == r.F_star for r in rows)
    prec = sum(len(r.families[0] & r.F_star) / len(r.families[0]) for r in rows)
    rec = sum(len(r.families[0] & r.F_star) / len(r.F_star) for r in rows)
    n = len(rows)
    return {"n": n, "exact": exact / n, "precision": prec / n, "recall": rec / n}


def secondary(records: Sequence[QueryRecord]) -> dict[str, object]:
    """SPEC 10.3 (costs and storage are in `costs`)."""
    qs = query_sets(records)
    q_u = qs["Q_u"]
    q_c = qs["Q_c"]
    amb = [r for r in q_c if r.cell == "ambiguo"]
    abst = Counter(
        (r.cell, r.state, r.reason, r.outcome) for r in records
        if r.outcome in ("abstencao_apropriada", "abstencao_desnecessaria")
    )
    return {
        "unchanged_coverage": _ratio(sum(r.outcome == "correto_sustentado" for r in q_u), len(q_u)),
        "unchanged_false_attribution_rate": _ratio(sum(r.state in ATTRIBUTIONS for r in q_u), len(q_u)),
        "group_mean": group_mean(records, primary),
        "per_class": per_class_prf(records),
        "sets": set_metrics(records),
        "unduly_exclusive_rate": _ratio(sum(r.outcome == "indevidamente_exclusivo" for r in q_c), len(q_c)),
        "alternatives_identification": _ratio(sum(r.outcome == "correto_sustentado" for r in amb), len(amb)),
        "abstentions": {"|".join(k): v for k, v in sorted(abst.items())},
        "falha_by_method": {m: _ratio(sum(r.outcome == "falha" for r in rs), len(rs))
                            for m, rs in _by(records, lambda r: r.method).items()},
        "n_indeterminado": len(qs["Q_ind"]),
        "n_incompleta": len(qs["Q_inc"]),
        "stability": stability(records),
    }


def group_mean(records: Sequence[QueryRecord], fn: Callable[[Sequence[QueryRecord]], Mapping[str, float]]) -> dict:
    """Metric per group, then the unweighted mean over groups that have a denominator."""
    per = [fn(rs) for rs in _by(records, lambda r: r.group).values()]
    keys = ("cobertura", "cobertura_bruta", "risco_seletivo", "risco_comprometido")
    return {k: _ratio(sum(p[k] for p in per), len(per)) for k in keys} if per else {}


def stability(records: Sequence[QueryRecord]) -> float:
    """Fraction of (method, view, capability, budget, contrast, qid) whose outputs agree across repetitions."""
    by = _by(records, lambda r: (r.method, r.view, r.capability, r.budget, r.contrast, r.qid))
    multi = [rs for rs in by.values() if len({r.repetition for r in rs}) > 1]
    same = sum(len({(r.state, r.families) for r in rs}) == 1 for rs in multi)
    return _ratio(same, len(multi)) if multi else 1.0


def costs(items: Iterable[Cost]) -> dict[str, float]:
    """Raw cost per contrast and cost amortized per query (SPEC 10.3)."""
    items = list(items)
    n_q = sum(c.n_queries for c in items)
    out: dict[str, float] = {"n_contrasts": len(items), "n_queries": n_q}
    for f in ("evaluations", "bytes_read", "cpu_seconds"):
        tot = sum(getattr(c, f) for c in items)
        out[f"{f}_per_contrast"] = _ratio(tot, len(items))
        out[f"{f}_per_query"] = _ratio(tot, n_q)
    out["peak_rss_max"] = max((c.peak_rss for c in items), default=0)
    return out


def _by(records: Iterable, key: Callable) -> dict:
    out: dict = defaultdict(list)
    for r in records:
        out[key(r)].append(r)
    return dict(out)


def stratify(
    records: Sequence[QueryRecord],
    fn: Callable[[Sequence[QueryRecord]], Mapping] = primary,
    by: Sequence[str] = ("origin",),
) -> dict[tuple, Mapping]:
    """`fn` per stratum; the SPEC always reports by origin, and also by scenario family."""
    return {k: fn(rs) for k, rs in sorted(_by(records, lambda r: tuple(getattr(r, b) for b in by)).items())}
