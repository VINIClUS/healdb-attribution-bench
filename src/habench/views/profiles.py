"""Artifact kinds per evidence view (SPEC 7.1 table, 7.2 ablations and combined losses).

Imported by the method process: no `habench.pipeline`, `habench.oracle` or `habench.scenarios` here. The ablation
tables mirror `habench.oracle.truth` (a test checks that `split_view` agrees).

L3-R / L3-M show the same kinds as L2-R / L2-M: in the deterministic core the reference realizations repeat x0
(SPEC 7.1), so L3 needs no extra artifact kind.
"""

from __future__ import annotations

L1 = frozenset({"source_pt", "final", "hashes", "config_declared"})
L2_R = L1 | {"translation_en", "submitted_text", "acm_response", "code_link", "env_versions", "ops_actions"}
L2_M = L2_R | {"trace"}
N1 = frozenset({"source_pt", "final", "config_declared", "translation_en", "acm_response", "trace"})
N2 = N1 | {"submitted_text"}

BASES: dict[str, frozenset[str]] = {
    "L1": L1, "L2-R": L2_R, "L2-M": L2_M, "L3-R": L2_R, "L3-M": L2_M, "N1": N1, "N2": N2,
}
BASE_ORDER = ("L2-R", "L2-M", "L3-R", "L3-M", "L1", "N1", "N2")  # prefix match order of split_view

ABLATIONS = {"A1": "submitted_text", "A2": "acm_response", "A3": "code_link", "A4": "env_versions",
             "A5": "ops_actions", "A6": "trace"}
REPLACEMENTS = {"A2": "acm_response_top1", "A6": "trace_winners"}
COMBINED = {"C1": ("A1", "A3"), "C2": ("A2", "A6"), "C3": ("A3", "A4", "A5"), "C4": ("A1", "A2", "A3")}
WINNERS_BASES = ("L2-M", "L3-M")  # A6 is defined only with a trace to reduce (SPEC 7.2)


def split_view(view: str) -> tuple[str, tuple[str, ...]]:
    """"L2-R-A3" -> ("L2-R", ("A3",)); "L2-M-C2" -> ("L2-M", ("A2", "A6"))."""
    for base in BASE_ORDER:
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


def kinds(view: str) -> frozenset[str]:
    """Artifact kinds visible in `view`. ValueError for an unknown view or an ablation whose item is absent."""
    base, abl = split_view(view)
    out = set(BASES[base])
    for a in abl:
        item = ABLATIONS[a]
        if item not in out:
            raise ValueError(f"{view!r}: ablation {a} removes {item!r}, absent from {base}")
        if a == "A6" and base not in WINNERS_BASES:
            raise ValueError(f"{view!r}: A6 is valid only on L2-M/L3-M")
        out.discard(item)
        if a in REPLACEMENTS:
            out.add(REPLACEMENTS[a])
    return frozenset(out)
