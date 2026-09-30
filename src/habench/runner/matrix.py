"""The efficient run matrix (SPEC §7.3, §12; protocol §8.2, §10): which (view, capability, budget, method) cells run.

- Algorithm comparisons share a view: every method on L2-R and L2-M under R-A at every budget, and on L1, L2-R,
  L2-M under R-C at the primary budget.
- Information comparisons share the algorithm (M): family I crosses M with every view, ablation and capability,
  over the runs of F/M/O/X and its own divergence runs.
- Structural n/a cells (L1 × R-A/R-B) are never run. Equivalent cells are run once and reported as equal:
  R-B ≡ R-A when D has no prep factor (every local contrast), L3 ≡ L2 in the deterministic core.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

BUDGETS = (16, 32, 64)
PRIMARY_BUDGET = 16  # H1a (SPEC 7.4, D7.9)
METHODS = {
    "b0": "habench.methods.b0:B0",
    "b1": "habench.methods.b1:B1",
    "b2": "habench.methods.b2:B2",
    "b3": "habench.methods.b3:B3",
    "bugdoc": "habench.methods.bugdoc_adapter:BugDocMethod",
    "m": "habench.methods.m:M",
    "m_lenient": "habench.methods.m:MLenient",  # the rigor sweep, cal only (SPEC 13.5)
}
DEFAULT_METHODS = ("b0", "b1", "b2", "b3", "bugdoc", "m")
INFO_VIEWS = (
    "L1", "L2-R", "L2-M", "N1", "N2",
    "L2-R-A1", "L2-R-A2", "L2-R-A3", "L2-R-A4", "L2-R-A5",
    "L2-M-A1", "L2-M-A2", "L2-M-A3", "L2-M-A4", "L2-M-A5", "L2-M-A6",
    "L2-R-C1", "L2-R-C3", "L2-R-C4", "L2-M-C1", "L2-M-C2", "L2-M-C3", "L2-M-C4",
)
CAPABILITIES = ("R-A", "R-B", "R-C")


@dataclass(frozen=True, slots=True, order=True)
class Cell:
    view: str
    capability: str
    budget: int
    method: str
    equivalent_to: tuple[str, str] | None = None  # (view, capability) actually run, for reported-equal cells

    @property
    def runs(self) -> bool:
        return self.equivalent_to is None


def structural_na(view: str, capability: str) -> bool:
    return view == "L1" and capability != "R-C"


def _equivalent(view: str, capability: str, has_prep: bool) -> tuple[str, str] | None:
    if view.startswith("L3-"):
        return "L2-" + view[3:], capability
    if capability == "R-B" and not has_prep:
        return view, "R-A"
    return None


def cells(
    family: str, *, has_prep: bool = False, methods: Iterable[str] = DEFAULT_METHODS, info_cross: bool | None = None
) -> list[Cell]:
    """Cells for one contrast of scenario `family` (N, F, M, O, X or I).

    `info_cross` (default: family I only) crosses M with every view and capability; the runner turns it on for a
    seeded sample of F/M/O/X contrasts, which are family I's "same executions" (SPEC 12).
    """
    methods = tuple(methods)
    wanted: set[tuple[str, str, int, str]] = set()
    for m in methods:
        for view in ("L2-R", "L2-M"):
            for b in BUDGETS:
                wanted.add((view, "R-A", b, m))
            wanted.add((view, "R-B", PRIMARY_BUDGET, m))
        for view in ("L1", "L2-R", "L2-M"):
            wanted.add((view, "R-C", PRIMARY_BUDGET, m))
    if (family == "I" if info_cross is None else info_cross) and "m" in methods:
        for view in INFO_VIEWS:
            for cap in CAPABILITIES:
                wanted.add((view, cap, PRIMARY_BUDGET, "m"))
        wanted.update(("L3-" + v[3:], cap, PRIMARY_BUDGET, "m") for v in ("L2-R", "L2-M") for cap in CAPABILITIES)
    out = []
    for view, cap, b, m in sorted(wanted):
        if structural_na(view, cap):
            continue
        out.append(Cell(view, cap, b, m, _equivalent(view, cap, has_prep)))
    return out
