"""The truth package of a contrast (SPEC §6, §8.3, §9.3). Never visible to methods.

Per query: key, endpoint presences, eligibility, change, `F*`/`F*_adm`, completeness, non-monotone flag,
the admissible truth table, and per cell (view, capability) the identification bounds `W_lo`/`W_hi`
and state. Per contrast: the budget necessity per cell, the scenario family and the origin.

`origin` ("real" or "semisynthetic": D contains a `patch:*`, SPEC 10.3) lives only here; so do the patch
contents, through the contrast copy.

Cell identifiers: `(view, capability)`, with view ids such as "L1", "L2-R", "L2-M", "N1", "N2", and
ablated views written as "<base>-<ablation>" ("L2-R-A3", "L2-M-A6", "L2-R-C1"); capabilities "R-A",
"R-B", "R-C".
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from habench.oracle import families as fam_mod
from habench.oracle.contrast import Contrast, canonical_json
from habench.types import AssocKey, Family, Presence, SealedError

IDENT_STATES = ("identificado", "ambiguo", "indeterminado")
CELLS = ("identificado", "ambiguo", "indeterminado", "incompleta", "inalterado")
CAPABILITIES = ("R-A", "R-B", "R-C")
Cell = tuple[str, str]  # (view, capability)


# ---------------------------------------------------------------------- views and cells


ABLATIONS = {
    "A1": "submitted_text", "A2": "acm_response", "A3": "code_link", "A4": "env_versions",
    "A5": "ops_actions", "A6": "trace",
}
COMBINED = {"C1": ("A1", "A3"), "C2": ("A2", "A6"), "C3": ("A3", "A4", "A5"), "C4": ("A1", "A2", "A3")}


def split_view(view: str) -> tuple[str, tuple[str, ...]]:
    """"L2-R-A3" -> ("L2-R", ("A3",)); "L2-M-C2" -> ("L2-M", ("A2", "A6"))."""
    for base in ("L2-R", "L2-M", "L3-R", "L3-M", "L1", "N1", "N2"):
        if view == base:
            return base, ()
        if view.startswith(base + "-"):
            tag = view[len(base) + 1:]
            if tag in ABLATIONS:
                return base, (tag,)
            if tag in COMBINED:
                return base, COMBINED[tag]
            raise ValueError(f"unknown ablation in view {view!r}")
    raise ValueError(f"unknown view {view!r}")


@dataclass(frozen=True)
class CellSpec:
    """What a cell gives the reference search (SPEC 7.1-7.3, 8.4, 9.3)."""

    view: str
    capability: str
    evidence: bool  # the view shows responses (full or top-1): dummy pruning allowed
    full_response: bool  # full response (not A2)
    code_link: bool  # the broker replays executed levels (else declared, 5.4)
    runs_hybrids: bool  # the capability executes hybrids at all
    no_prep: bool  # R-B: only S without prep factors

    @classmethod
    def of(cls, view: str, capability: str) -> CellSpec:
        if capability not in CAPABILITIES:
            raise ValueError(capability)
        base, abl = split_view(view)
        if base == "L1" and capability != "R-C":
            raise ValueError("L1 exists only with R-C (SPEC 7.3)")
        evidence = base != "L1"
        full = evidence and "A2" not in abl
        link = base in ("L2-R", "L2-M", "L3-R", "L3-M") and "A3" not in abl
        return cls(view, capability, evidence, full, link, capability != "R-C", capability == "R-B")

    def u_needed(self, has_prep: bool) -> bool:
        """SPEC 8.4: U is not needed with the full response, the code link and every admissible S executable."""
        full = self.full_response and not (has_prep and "A1" in split_view(self.view)[1])
        runs_all = self.capability == "R-A" or (self.capability == "R-B" and not has_prep)
        n_view = split_view(self.view)[0] in ("N1", "N2")
        return not (full and self.code_link and runs_all and not n_view)


# ---------------------------------------------------------------------- identification


@dataclass(frozen=True)
class Identification:
    W_lo: frozenset[Family]
    W_hi: frozenset[Family]
    saturated: bool
    note: str = ""

    def __post_init__(self) -> None:
        if not self.W_lo or not self.W_lo <= self.W_hi:
            raise ValueError("W_lo must be non-empty and contained in W_hi (SPEC 8.3)")

    @property
    def state(self) -> str:
        """SPEC 8.3: ambiguo if |W_lo| >= 2; identificado if W_lo = W_hi singleton and saturated."""
        if len(self.W_lo) >= 2:
            return "ambiguo"
        if self.W_lo == self.W_hi and self.saturated:
            return "identificado"
        return "indeterminado"

    @classmethod
    def singleton(cls, F: Family, note: str = "U not needed (SPEC 8.4)") -> Identification:
        return cls(frozenset({F}), frozenset({F}), True, note)


# ---------------------------------------------------------------------- per query / per contrast


@dataclass(frozen=True)
class QueryTruth:
    qid: str
    key: AssocKey
    x0: Presence
    x1: Presence
    changed: bool
    family: Family | None  # F*_adm (equal to F* when complete); None if unchanged or ineligible
    complete: bool | None
    nonmonotone: bool | None
    table: Mapping[frozenset[str], Presence]  # admissible S only
    ident: Mapping[Cell, Identification] = field(default_factory=dict)

    @property
    def eligible(self) -> bool:
        return Presence.UNAVAILABLE not in (self.x0, self.x1)

    @property
    def F_star(self) -> Family | None:
        return self.family if self.complete else None

    @property
    def F_adm(self) -> Family | None:
        return self.family if self.complete is False else None

    def cell(self, view: str, capability: str) -> str:
        """SPEC 9.3 truth cell. Raises ValueError for an ineligible query, KeyError for a missing cell."""
        if not self.eligible:
            raise ValueError(f"{self.qid} is ineligible")
        if not self.changed:
            return "inalterado"
        if not self.complete:
            return "incompleta"
        return self.ident[(view, capability)].state

    def sufficient(self, S: Iterable[str]) -> bool | None:
        """suff(S) (SPEC 6.1); None for an inadmissible S."""
        S = frozenset(S)
        if S not in self.table:
            return None
        D = max(self.table, key=len)
        return self.table[S] == self.table[D]

    def is_dummy(self, f: str) -> bool:
        """True irrelevance of f on the admissible table (SPEC 4.6 definition)."""
        return all(self.table[S | {f}] == st for S, st in self.table.items() if f not in S and S | {f} in self.table)


@dataclass(frozen=True)
class ContrastTruth:
    contrast: Contrast
    partition: str
    scenario_family: str
    queries: tuple[QueryTruth, ...]
    necessity: Mapping[Cell, int]
    valid: bool = True
    invalid_reason: str = ""

    @property
    def origin(self) -> str:
        return "semisynthetic" if any(f.startswith("patch:") for f in self.contrast.D) else "real"

    @property
    def cid(self) -> str:
        return self.contrast.cid

    def query(self, qid: str) -> QueryTruth:
        return next(q for q in self.queries if q.qid == qid)

    def budget_abstention_appropriate(self, view: str, capability: str, budget: int) -> bool:
        """SPEC 9.3: `orcamento_esgotado` is appropriate iff the necessity exceeds the budget."""
        return self.necessity[(view, capability)] > budget

    # ------------------------------------------------------------------ JSON

    def to_json(self) -> dict:
        return {
            "contrast": self.contrast.to_json(),
            "contrast_hash": self.contrast.content_hash(),
            "partition": self.partition,
            "scenario_family": self.scenario_family,
            "origin": self.origin,
            "valid": self.valid,
            "invalid_reason": self.invalid_reason,
            "necessity": [[v, c, n] for (v, c), n in sorted(self.necessity.items())],
            "queries": [_query_json(q) for q in self.queries],
        }

    @classmethod
    def from_json(cls, obj: Mapping) -> ContrastTruth:
        c = Contrast.from_json(obj["contrast"])
        if c.content_hash() != obj["contrast_hash"]:
            raise ValueError("contrast hash mismatch")
        return cls(
            contrast=c,
            partition=obj["partition"],
            scenario_family=obj["scenario_family"],
            queries=tuple(_query_from(q) for q in obj["queries"]),
            necessity={(v, cap): n for v, cap, n in obj["necessity"]},
            valid=obj["valid"],
            invalid_reason=obj["invalid_reason"],
        )


def _sets_json(F: Iterable[Iterable[str]]) -> list[list[str]]:
    return sorted(sorted(S) for S in F)


def _family_json(F: Family | None) -> list | None:
    return None if F is None else _sets_json(F)


def _family_from(obj: list | None) -> Family | None:
    return None if obj is None else frozenset(frozenset(S) for S in obj)


def _query_json(q: QueryTruth) -> dict:
    return {
        "qid": q.qid,
        "key": [q.key.med, q.key.system, q.key.version, q.key.code],
        "x0": q.x0.value,
        "x1": q.x1.value,
        "changed": q.changed,
        "family": _family_json(q.family),
        "complete": q.complete,
        "nonmonotone": q.nonmonotone,
        "table": sorted([sorted(S), st.value] for S, st in q.table.items()),
        "ident": [
            {"view": v, "capability": c, "W_lo": sorted(_family_json(F) for F in i.W_lo),
             "W_hi": sorted(_family_json(F) for F in i.W_hi), "saturated": i.saturated, "note": i.note}
            for (v, c), i in sorted(q.ident.items())
        ],
    }


def _query_from(obj: Mapping) -> QueryTruth:
    return QueryTruth(
        qid=obj["qid"],
        key=AssocKey(*obj["key"]),
        x0=Presence(obj["x0"]),
        x1=Presence(obj["x1"]),
        changed=obj["changed"],
        family=_family_from(obj["family"]),
        complete=obj["complete"],
        nonmonotone=obj["nonmonotone"],
        table={frozenset(S): Presence(st) for S, st in obj["table"]},
        ident={
            (i["view"], i["capability"]): Identification(
                frozenset(_family_from(F) for F in i["W_lo"]), frozenset(_family_from(F) for F in i["W_hi"]),
                i["saturated"], i["note"],
            )
            for i in obj["ident"]
        },
    )


def write_truth(t: ContrastTruth, path: Path) -> None:
    if t.partition == "test":
        raise SealedError("test truth is never materialized before the freeze")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_json(t.to_json()) + "\n", encoding="utf-8")


def read_truth(path: Path) -> ContrastTruth:
    return ContrastTruth.from_json(json.loads(path.read_text(encoding="utf-8")))


# ---------------------------------------------------------------------- builder


IdentFn = Callable[[QueryTruth, CellSpec], Identification]
DummyFn = Callable[[object, AssocKey, str], bool]  # (hybrids in use, key, factor) -> sound certificate

N1_TRAITS = frozenset({"v1", "v1_hyp_le_0.6", "v1_no_required"})
N1_MAPS = frozenset({"cm_gated", "cm_ungated"})


def default_expressible(cs: CellSpec, hybrids, S: frozenset[str]) -> bool:
    """SPEC 7.1: N1 replays ent_thr, icd_thr, trait among the V1 rules and the map gate; N2 only the thresholds.
    Patches are evidence edits and stay expressible; every other view expresses every S."""
    base = split_view(cs.view)[0]
    if base not in ("N1", "N2"):
        return True
    for f in S:
        if f.startswith("patch:"):
            continue
        for x in hybrids.contrast.components(f):
            if x in ("ent_thr", "icd_thr"):
                continue
            levels = {hybrids.base0.get(x), hybrids.base1.get(x)}
            if base == "N1" and x == "trait" and levels <= N1_TRAITS:
                continue
            if base == "N1" and x == "map" and levels <= N1_MAPS:
                continue
            return False
    return True


def build_truth(
    hybrids,  # habench.oracle.hybrids.Hybrids on the executed levels
    queries: Sequence[tuple[str, AssocKey]],
    *,
    partition: str,
    scenario_family: str,
    cells: Iterable[CellSpec] = (),
    ident: IdentFn | None = None,
    dummy: DummyFn | None = None,
    declared_hybrids=None,  # Hybrids on the declared levels, for cells without the code link
    expressible: Callable[[CellSpec, object, frozenset[str]], bool] = default_expressible,
    recorded: Mapping[str, tuple[Presence, Presence]] | None = None,
) -> ContrastTruth:
    """Truth of one contrast.

    - Identification per cell: singleton `{F*}` when U is not needed (SPEC 8.4); otherwise `ident(q, cell)`
      (habench.oracle.identify). Without `ident`, cells that need U are left out.
    - Necessity per cell: 0 when the capability runs no hybrid; otherwise the joint reference BFS on the
      broker's replay (executed levels with the code link, declared without), with dummy pruning only if
      the view shows the full response (`dummy(hybrids_in_use, key, f)`, default `oracle.dummies.certificate`,
      must be sound) and with `expressible` restricting S (N1/N2 by default, SPEC 7.1).
    - `recorded[qid] = (x0, x1)`: presences recorded by the executed runs; a mismatch with h_∅/h_D marks the
      contrast invalid (SPEC 5.4).
    """
    if dummy is None:
        from habench.oracle import dummies

        dummy = dummies.certificate
    if partition == "test":
        raise SealedError("the test partition is sealed")
    c: Contrast = hybrids.contrast
    D = frozenset(hybrids.D)
    qts: list[QueryTruth] = []
    for qid, key in queries:
        table = hybrids.truth_table(key)
        x0, x1 = table[frozenset()], table[D]
        eligible = Presence.UNAVAILABLE not in (x0, x1)
        if eligible:
            r = fam_mod.analyze(D, table)
            qts.append(QueryTruth(qid, key, x0, x1, r.changed, r.family, r.complete, r.nonmonotone, table))
        else:
            qts.append(QueryTruth(qid, key, x0, x1, False, None, None, None, table))
    cells = list(cells)
    has_prep = bool(c.prep_factors)
    final: list[QueryTruth] = []
    for q in qts:
        idents: dict[Cell, Identification] = {}
        if q.eligible and q.changed and q.complete:
            for cs in cells:
                if not cs.u_needed(has_prep):
                    idents[(cs.view, cs.capability)] = Identification.singleton(q.family)
                elif ident is not None:
                    try:
                        idents[(cs.view, cs.capability)] = ident(q, cs)
                    except NotImplementedError:
                        pass  # the reference does not cover this cell yet: the cell stays out of the truth
        final.append(QueryTruth(q.qid, q.key, q.x0, q.x1, q.changed, q.family, q.complete, q.nonmonotone,
                                q.table, idents))
    necessity: dict[Cell, int] = {}
    for cs in cells:
        necessity[(cs.view, cs.capability)] = _necessity(
            cs, hybrids, declared_hybrids, final, dummy, expressible
        )
    reason = ""
    if not hybrids.endpoints_reproduce():
        reason = "h_∅/h_D configs differ from the recorded x0/x1 (SPEC 5.4)"
    for q in final:
        if recorded is not None and q.qid in recorded and tuple(recorded[q.qid]) != (q.x0, q.x1):
            reason = f"{q.qid}: h_∅/h_D presences differ from the recorded runs (SPEC 5.4)"
            break
    return ContrastTruth(c, partition, scenario_family, tuple(final), necessity, valid=not reason,
                         invalid_reason=reason)


def _necessity(cs: CellSpec, hybrids, declared_hybrids, queries: Sequence[QueryTruth], dummy, expressible) -> int:
    if not cs.runs_hybrids:
        return 0  # SPEC 9.3 (A13)
    h = hybrids if cs.code_link or declared_hybrids is None else declared_hybrids
    prep = set(h.contrast.prep_factors)

    def admissible(S: frozenset[str]) -> bool:
        if not h.admissible(S):
            return False
        if cs.no_prep and S & prep:
            return False
        return expressible(cs, h, S)

    open_q = [q for q in queries if q.eligible]
    qfun = {q.qid: (lambda S, key=q.key: h.state(S, key)) for q in open_q}
    dummies = {}
    if cs.full_response:
        dummies = {q.qid: frozenset(f for f in h.D if dummy(h, q.key, f)) for q in open_q}
    return fam_mod.necessity(h.D, qfun, admissible=admissible, dummies=dummies)
