"""Static irrelevance certificates for one factor and one association (design §B1).

`dummy(f, a, x0, x1, ...)` returns True only when it proves that switching f between its x0 and x1
levels never changes the state of `a`, whatever the levels of the other factors of the contrast:
for every S ⊆ D \\ {f}, state_S(a) == state_{S ∪ {f}}(a). Otherwise it returns None ("cannot
decide"); it never returns False. The proofs read only the evidence of `a.med` (its parsed
response and the hierarchy); they never evaluate hybrids. Thresholds are the only factors treated
as monotone; nothing else is assumed monotone.

"Relevant candidates" of `a` are the candidates of `a.med` whose code reaches `a.code` under either
`map` level of the contrast, in every patch variant of the contrast. A record contributing to `a`
takes its scalars from one of them and its traits from their entities (or entities sharing an Id).
"""

from __future__ import annotations

import itertools
from collections.abc import Mapping

from habench.pipeline import catalog, core
from habench.pipeline.catalog import Config, TraitRule
from habench.pipeline.core import WHO, KeySpace
from habench.pipeline.evidence import STATUS_FAILED, STATUS_MISSING, Evidence, Patch
from habench.pipeline.mapping import Hierarchy
from habench.types import AssocKey

MAX_TRAIT_ENTITIES = 10  # enumeration cap of the trait proof; above it the answer is None


def _variants(a: AssocKey, x0: Config, x1: Config, ev: Evidence, patches: Mapping[str, Patch] | None) -> list[Evidence]:
    """Single-medication evidence of `a.med` under every patch subset of the contrast that touches it."""
    base = ev.subset([a.med])
    # patches on other medications cannot change this medication's evidence
    names = sorted(x0.patches_on() | x1.patches_on())
    touching = [p for p in names if a.med in (patches or {})[p].meds]
    out = []
    for r in range(len(touching) + 1):
        for sub in itertools.combinations(touching, r):
            out.append(base.patched(patches[p] for p in sub) if sub else base)  # type: ignore[index]
    return out


def _reaches(ev: Evidence, hier: Hierarchy, level: str, space: KeySpace, code_ix: int, target: str) -> bool:
    """Whether a record with this code, passing everything else, would contribute to key code `target`."""
    gate, keycode = core._code_map(ev, hier, level, WHO)[0], core._code_map(ev, hier, level, space)[1]
    return bool(gate[code_ix]) and keycode[code_ix] == target


def _relevant(ev: Evidence, hier: Hierarchy, levels: set[str], space: KeySpace, a: AssocKey) -> list[int]:
    return [
        c for c in range(len(ev.c_med))
        if any(core._code_map(ev, hier, lv, space)[1][ev.c_code[c]] == a.code for lv in levels)
    ]


def _same_order_per_code(ev: Evidence, rel: list[int], kept: list[int]) -> bool:
    """Per code, the relevant candidates appear in the same relative order in emission and in `kept` (EX-30)."""
    rs = set(rel)

    def per_code(seq) -> dict[int, list[int]]:
        out: dict[int, list[int]] = {}
        for c in seq:
            if c in rs:
                out.setdefault(int(ev.c_code[c]), []).append(c)
        return out

    return per_code(range(len(ev.c_med))) == per_code(kept)


def _rule_verdict(rule: TraitRule, names: set[str], hyp: float | None, has_hyp: bool, tp: str) -> bool:
    if rule.veto & names:
        return False
    if rule.hyp_veto_gt is not None and has_hyp and (hyp or 0) > rule.hyp_veto_gt:
        return False
    if rule.required is not None:
        ok = bool(rule.required & names) or (has_hyp and (hyp or 0) <= rule.hyp_ok_le)
        if not ok:
            return False
    return rule.entity_type is None or tp == rule.entity_type


def _trait_equal(ev: Evidence, rel: list[int], l0: str, l1: str) -> bool | None:
    r0, r1 = catalog.TRAIT_RULES[l0], catalog.TRAIT_RULES[l1]
    ents = {int(ev.c_ent[c]) for c in rel}
    eids = {(int(ev.e_med[e]), int(ev.e_eid[e])) for e in ents}
    ents |= {e for e in range(len(ev.e_med)) if (int(ev.e_med[e]), int(ev.e_eid[e])) in eids}
    types = {ev.types[ev.c_type[c]] for c in rel}
    pool = sorted(ents)
    if len(pool) > MAX_TRAIT_ENTITIES:
        return None
    for r in range(1, len(pool) + 1):
        for sub in itertools.combinations(pool, r):
            names = {n for e in sub for n, _ in ev.e_traits[e]}
            hyps = {s for e in sub for n, s in ev.e_traits[e] if n == "HYPOTHETICAL"}
            for hyp in hyps or {None}:
                for tp in types:
                    has = bool(hyps)
                    if _rule_verdict(r0, names, hyp, has, tp) != _rule_verdict(r1, names, hyp, has, tp):
                        return None
    return True


def dummy(
    f: str,
    a: AssocKey,
    x0: Config,
    x1: Config,
    ev: Evidence,
    hier: Hierarchy,
    space: KeySpace = WHO,
    patches: Mapping[str, Patch] | None = None,
) -> bool | None:
    """True if f provably never changes the state of `a` in the contrast (x0, x1); None otherwise."""
    D = x0.diff(x1)
    if f not in D:
        return True
    if ev.status(a.med) in (STATUS_FAILED, STATUS_MISSING):
        return True  # UNAVAILABLE under every hybrid
    fac = catalog.factor(f)
    if fac.stage in ("prep", "acm"):
        return None
    if fac.stage == "patch":
        p = (patches or {}).get(f[len("patch:"):])
        return True if p is not None and a.med not in p.meds else None
    maps = {str(x0["map"]), str(x1["map"])}
    for v in _variants(a, x0, x1, ev, patches):
        rel = _relevant(v, hier, maps, space, a)
        if not rel:
            continue  # no candidate can ever reach `a` in this variant
        if f in catalog.THRESHOLDS:
            lo, hi = sorted((float(x0[f]), float(x1[f])))
            col = v.c_es if f == "ent_thr" else v.c_cs
            if any(lo <= col[c] < hi for c in rel):
                return None
        elif f == "map":
            l0, l1 = str(x0["map"]), str(x1["map"])
            for ci in range(len(v.codes)):
                if _reaches(v, hier, l0, space, ci, a.code) != _reaches(v, hier, l1, space, ci, a.code):
                    return None
        elif f == "sel":
            top = core._select(v, "top1")
            if any(c not in set(top) for c in rel) or not _same_order_per_code(v, rel, top):
                return None
        elif f == "occ":
            codes = [int(v.c_code[c]) for c in rel]
            if len(codes) != len(set(codes)):
                return None
            eids = [int(v.e_eid[v.c_ent[c]]) for c in rel]
            if len(eids) != len(set(eids)) or any(
                sum(1 for e in range(len(v.e_med)) if int(v.e_eid[e]) == eid) > 1 for eid in eids
            ):
                return None
            # a trait name repeated inside the entity with other scores: first_upsert keeps the first score
            if any(len(dict(v.e_traits[v.c_ent[c]])) != len(set(v.e_traits[v.c_ent[c]])) for c in rel):
                return None
        elif f == "trait":
            if _trait_equal(v, rel, str(x0["trait"]), str(x1["trait"])) is None:
                return None
        else:
            return None
    return True
