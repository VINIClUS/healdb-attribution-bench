"""Reference dummy certificates for the oracle (SPEC 4.6), on the realized configs of a contrast.

Wraps `pipeline.semantics.dummy` (lead α) and adds the order condition of rule 2 (`sel`, EX-30) that it
lacks: the relevant candidates of each code must keep their relative order between emission and the
`top1` output, which follows the first appearance of each Id group (SPEC 3.2 step 3).
Bundles are never certified (joint irrelevance does not follow from the components).
"""

from __future__ import annotations

from habench.pipeline import core, semantics
from habench.pipeline.evidence import Evidence
from habench.types import AssocKey


def _sel_order_ok(ev: Evidence, hier, levels: set[str], space, a: AssocKey) -> bool:
    """Every relevant candidate keeps its relative order, per code, from emission to the top1 output."""
    maps = [core._code_map(ev, hier, lv, space)[1] for lv in levels]
    med_c = [c for c in range(len(ev.c_med)) if int(ev.c_med[c]) == a.med]
    rel = {c for c in med_c if any(m[ev.c_code[c]] == a.code for m in maps)}

    def per_code(seq):
        out: dict[int, list[int]] = {}
        for c in seq:
            if c in rel:
                out.setdefault(int(ev.c_code[c]), []).append(c)
        return out

    return per_code(range(len(ev.c_med))) == per_code(core._select(ev, "top1"))


def certificate(hybrids, key: AssocKey, f: str) -> bool:
    """True iff the reference rules prove f irrelevant for `key` in the contrast of `hybrids`."""
    c = hybrids.contrast
    if f in c.bundle_map or f in c.prep_factors:
        return False
    x0, x1 = hybrids.config(frozenset()), hybrids.config(frozenset(hybrids.D))
    if f not in x0.diff(x1):
        return True  # not in D, or its realized level is the same in both runs
    ev = hybrids.evidence
    verdict = semantics.dummy(f, key, x0, x1, ev, hybrids.hier, hybrids.space, c.patch_map)
    if verdict is not True:
        return False
    if f == "sel" and ev.status(key.med) not in ("failed", "missing"):
        levels = {str(x0["map"]), str(x1["map"])}
        for v in semantics._variants(key, x0, x1, ev, c.patch_map):
            if not _sel_order_ok(v, hybrids.hier, levels, hybrids.space, key):
                return False
    return True
