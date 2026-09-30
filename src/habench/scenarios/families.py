"""Candidate contrasts of the families N, F, M, O and I (SPEC 12), as lazy generators in preference order.

Each generator yields `Candidate`s; `base.take` assesses them with the oracle until the per-group target is met.
Real-data coverage of a candidate (whether some query changes) is always decided by the oracle, never assumed.
"""

from __future__ import annotations

from collections.abc import Iterator

from habench.pipeline import catalog, mapping, semantics
from habench.pipeline.catalog import V1
from habench.scenarios import patches as P
from habench.scenarios.base import Candidate, Ctx
from habench.scenarios.levels import DEV_CAL_THRESHOLDS

EntityRow = tuple[int, int, dict]  # (medication, array position, entity)


# ---------------------------------------------------------------------- evidence scans


def entity_rows(ctx: Ctx) -> list[EntityRow]:
    """Entities with concepts (the ones that produce candidates), by medication and position."""
    return [(m, i, e) for m in sorted(ctx.docs) for i, e in enumerate(ctx.docs[m].get("Entities") or [])
            if e.get("ICD10CMConcepts")]


def trait_ok(ent: dict, level: str = "v1") -> bool:
    """The entity's own traits and type pass the trait rule `level` (a one-entity record)."""
    traits = ent.get("Traits") or []
    names = {t["Name"] for t in traits if t.get("Name")}
    hyps = [t.get("Score") for t in traits if t.get("Name") == "HYPOTHETICAL"]
    return semantics._rule_verdict(catalog.TRAIT_RULES[level], names, hyps[0] if hyps else None, bool(hyps),
                                   ent.get("Type"))


def multiplicity(ctx: Ctx) -> int:
    """Repeated candidates of the group: extra occurrences of a (medication, code) plus repeated entity Ids."""
    n = 0
    for m, doc in sorted(ctx.docs.items()):
        ents = doc.get("Entities") or []
        codes = [c.get("Code") for e in ents for c in e.get("ICD10CMConcepts") or []]
        ids = [e.get("Id") for e in ents]
        n += (len(codes) - len(set(codes))) + (len(ids) - len(set(ids)))
    return n


def score_values(ctx: Ctx, factor: str) -> list[float]:
    """Every entity score (ent_thr) or concept score (icd_thr) of the group's candidates."""
    out = []
    for _, _, e in entity_rows(ctx):
        if factor == "ent_thr":
            if e.get("Score") is not None:
                out.append(float(e["Score"]))
        else:
            out.extend(float(c["Score"]) for c in e["ICD10CMConcepts"] if c.get("Score") is not None)
    return out


def empty_band(ctx: Ctx, factor: str, t0: float, t1: float) -> bool:
    """No candidate score in [min(t0, t1), max(t0, t1)): moving the threshold cannot change any record."""
    lo, hi = sorted((t0, t1))
    return not any(lo <= v < hi for v in score_values(ctx, factor))


def others_pass(ctx: Ctx, factor: str, ent: dict) -> list[int]:
    """Concept positions of `ent` that pass every V1 predicate except the threshold of `factor`."""
    if not trait_ok(ent):
        return []
    base = float(catalog.V1["ent_thr"])
    if factor == "icd_thr" and not (ent.get("Score") is not None and ent["Score"] >= base):
        return []
    out = []
    for j, c in enumerate(ent["ICD10CMConcepts"]):
        if not mapping.v1_gate(ctx.hier, c.get("Code") or ""):
            continue
        if factor == "ent_thr" and not (c.get("Score") is not None and c["Score"] >= float(catalog.V1["icd_thr"])):
            continue
        out.append(j)
    return out


def border_patch(ctx: Ctx, factor: str, t1: float, value: float, *, above: float | None = None) -> P.Patch | None:
    """A valid patch setting the score nearest to `t1` (among records passing the other V1 predicates) to `value`.
    With `above`, only scores strictly greater than it are candidates for the edit."""
    rows = []
    for m, i, e in entity_rows(ctx):
        for j in others_pass(ctx, factor, e):
            score = float(e["Score"] if factor == "ent_thr" else e["ICD10CMConcepts"][j]["Score"])
            if above is not None and score <= above:
                continue
            rows.append((abs(score - t1), m, i, None if factor == "ent_thr" else e["ICD10CMConcepts"][j]["Code"]))
            if factor == "ent_thr":
                break
    for _, m, i, code in sorted(rows, key=lambda r: (r[0], r[1], r[2], r[3] or ""))[:30]:
        try:
            if factor == "ent_thr":
                return P.set_entity_score(ctx.docs, m, i, value)
            return P.set_concept_score(ctx.docs, m, i, code, value)
        except P.PatchError:
            continue
    return None


# ---------------------------------------------------------------------- N


def n_candidates(ctx: Ctx) -> Iterator[Candidate]:
    """N(a) D = empty; N(b) only dummy-certified factors (map in the WHO space, a threshold in an empty band).
    N(c) real repetition and N(d) simulator are not expressible as a single-evidence contrast (catalogue only)."""
    cfg = ctx.cfg.family("N")
    rng = ctx.rng("N")
    a = ctx.candidate("N", "a_empty_D", V1, V1, notes=(
        "N(c) real repetition and N(d) simulator are catalogued only (not a single-evidence contrast)",))
    if a:
        yield a
    m0, m1 = cfg["map_dummy"]
    map_c = ctx.candidate("N", "b_map", V1.with_(map=m0), V1.with_(map=m1), space="who")
    if map_c:
        yield map_c
    thr_c = []
    factors = list(cfg["threshold_factors"])
    rng.shuffle(factors)
    for f in factors:
        t0 = float(V1[f])
        levels = [t for t in DEV_CAL_THRESHOLDS[f] if t != t0 and empty_band(ctx, f, t0, t)]
        if not levels:
            ctx.report.drop("N", f"no_empty_band:{f}")
            continue
        c = ctx.candidate("N", "b_threshold_band", V1, V1.with_(**{f: rng.choice(sorted(levels))}))
        if c:
            thr_c.append(c)
            yield c
    if thr_c:
        both = ctx.candidate("N", "b_map_threshold", V1.with_(map=m0),
                             thr_c[0].contrast.x1.with_(map=m1), space="who")
        if both:
            yield both


# ---------------------------------------------------------------------- F


def f_plain(ctx: Ctx) -> Iterator[Candidate]:
    changes = [(f, lv) for f, lvs in ctx.cfg.family("F")["changes"].items() for lv in lvs]
    ctx.rng("F", "plain").shuffle(changes)
    for f, lv in changes:
        c = ctx.candidate("F", f, V1, V1.with_(**{f: lv}))
        if c:
            yield c


def f_border(ctx: Ctx) -> Iterator[Candidate]:
    """Semisynthetic variants: a patch sets a relevant score exactly to t1 and to t1 - epsilon (D = {thr, patch})."""
    F = ctx.cfg.family("F")
    eps = float(F["border"]["epsilon"])
    opts = [(f, float(lv)) for f in F["border"]["factors"] for lv in F["changes"][f]]
    ctx.rng("F", "border").shuffle(opts)
    for f, t1 in opts:
        for tag, value in (("border_eq", t1), ("border_minus", t1 - eps)):
            p = border_patch(ctx, f, t1, value)
            if p is None:
                ctx.report.drop("F", "no_valid_border_patch")
                continue
            c = ctx.candidate("F", tag, V1, V1.with_(**{f: t1}), patches=[p],
                              notes=(f"semisynthetic border patch on {f}",))
            if c:
                yield c


# ---------------------------------------------------------------------- M


def m_candidates(ctx: Ctx) -> Iterator[Candidate]:
    M = ctx.cfg.family("M")
    note = (str(M["granularity_note"]),)
    if M["extend"]:
        c = ctx.candidate("M", "extend", V1, V1.with_(map="cm_ungated"), space="cm",
                          bundles={"EXTEND": ("map",)}, notes=("bundle EXTEND in the CM space",))
        if c:
            yield c
    pairs = [tuple(p) for p in M["pairs"]]
    ctx.rng("M").shuffle(pairs)
    for a, b in pairs:
        c = ctx.candidate("M", f"{a}>{b}", V1.with_(map=a), V1.with_(map=b), space="who", notes=note)
        if c:
            yield c


def granularity_changes(changed: list, present0: frozenset, presentD: frozenset) -> int:
    """Keys k (4 characters) present in one run and absent in the other, with k[:3] present in the other (SPEC 2.1)."""
    n = 0
    for key in changed:
        code = key.code
        if len(code) != 4:
            continue
        parent = type(key)(key.med, key.system, key.version, code[:3])
        in0, inD = key in present0, key in presentD
        if (in0 and not inD and parent in presentD) or (inD and not in0 and parent in present0):
            n += 1
    return n


# ---------------------------------------------------------------------- O


def _swap_pair(ctx: Ctx) -> tuple[int, int, int] | None:
    """(med, a, b): two entities of one response that share a concept code."""
    rng = ctx.rng("O", "swap")
    pairs = []
    for m in sorted(ctx.docs):
        seen: dict[str, list[int]] = {}
        for i, e in enumerate(ctx.docs[m].get("Entities") or []):
            for c in e.get("ICD10CMConcepts") or []:
                pos = seen.setdefault(c.get("Code"), [])
                if i not in pos:
                    pos.append(i)
        pairs += [(m, pos[0], pos[1]) for _, pos in sorted(seen.items(), key=lambda kv: str(kv[0])) if len(pos) > 1]
    if not pairs:
        return None
    return rng.choice(sorted(set(pairs)))


def o_candidates(ctx: Ctx) -> Iterator[Candidate]:
    O = ctx.cfg.family("O")
    mult = multiplicity(ctx)
    if mult < int(O["min_multiplicity"]):
        ctx.report.drop("O", "low_multiplicity")
        return
    note = (f"candidate multiplicity {mult}",)
    cands = []
    for ch in O["changes"]:
        c = ctx.candidate("O", "+".join(sorted(ch)), V1, V1.with_(**ch), notes=note)
        if c:
            cands.append(c)
    if O["swap_patch"]:
        pair = _swap_pair(ctx)
        if pair is not None:
            try:
                p = P.swap_entities(ctx.docs, *pair)
            except P.PatchError:
                p = None
                ctx.report.drop("O", "swap_patch_invalid")
            c = p and ctx.candidate("O", "swap", V1, V1.with_(occ="first_upsert"), patches=[p],
                                    notes=(*note, "semisynthetic: swap of two entities sharing a code"))
            if c:
                cands.append(c)
    ctx.rng("O", "order").shuffle(cands)
    yield from cands


# ---------------------------------------------------------------------- I


def _bases(ctx: Ctx, label: str) -> list[tuple[str, float]]:
    F = ctx.cfg.family("F")["changes"]
    bases = [(f, float(lv)) for f in ("ent_thr", "icd_thr") for lv in F[f]]
    ctx.rng("I", label).shuffle(bases)
    return bases


def i_declared(ctx: Ctx, kind: str) -> Iterator[Candidate]:
    """New runs where the declared config differs from the executed one (SPEC 12 I(b)); thresholds as the F change."""
    for f, t in _bases(ctx, kind):
        x1_of = lambda x0: x0.with_(**{f: t})  # noqa: E731
        if kind == "trait":  # declared: documentation rule; executed: the code (EX-11)
            x0 = V1
            c = ctx.candidate("I", "declared_trait", x0, x1_of(x0), d0=V1.with_(trait="v1_hyp_le_0.6"),
                              notes=("declared d0 trait v1_hyp_le_0.6, executed v1",))
        elif kind == "map":  # declared gate, executed without (CM space)
            x0 = V1.with_(map="cm_ungated")
            c = ctx.candidate("I", "declared_map", x0, x1_of(x0), space="cm", d0=V1, d1=x1_of(V1),
                              notes=("declared cm_gated, executed cm_ungated",))
        elif kind == "occ":  # declared last occurrence, executed first
            x0 = V1.with_(occ="first_upsert")
            c = ctx.candidate("I", "declared_occ", x0, x1_of(x0), d0=V1, d1=x1_of(V1),
                              notes=("declared last_upsert, executed first_upsert",))
        else:
            raise ValueError(kind)
        if c:
            yield c


def i_alt(ctx: Ctx, kind: str) -> Iterator[Candidate]:
    """Runs that realize the `alt` variant (SPEC 4.3): the level label is the same, the behavior differs."""
    if kind == "threshold":
        for f in ("ent_thr", "icd_thr"):
            for t in DEV_CAL_THRESHOLDS[f]:
                if t in score_values(ctx, f):  # real data with a score exactly at t: `>` differs from `>=`
                    c = ctx.candidate("I", "alt_threshold", V1.with_(**{f: t}), V1.with_(**{f: t}),
                                      variants1=[f], notes=(f"alt variant: {f} > {t}",))
                    if c:
                        yield c
        p = border_patch(ctx, "ent_thr", 0.60, 0.60, above=0.60)  # semisynthetic: a score exactly at the V1 threshold
        if p is not None:
            c = ctx.candidate("I", "alt_threshold_border", V1, V1, variants1=["ent_thr"], patches=[p],
                              notes=("alt variant: ent_thr > 0.60", "semisynthetic border patch"))
            if c:
                yield c
        return
    spec = {
        "trait": ("alt_trait", "who"), "occ": ("alt_occ", "who"), "map": ("alt_map", "cm"),
    }[kind]
    c = ctx.candidate("I", spec[0], V1, V1, space=spec[1], variants1=[kind], notes=(f"alt variant of {kind}",))
    if c:
        yield c
