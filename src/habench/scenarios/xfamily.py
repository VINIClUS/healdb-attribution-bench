"""Family X (SPEC 12): (i) the V1_TO_V2 bundle and its components, (ii) oracle-guided rejection sampling with
shape quotas, (iii) the SPEC 7.2 example as a semisynthetic case. Dev/cal only.

Reading of "sem efeito verificado" and "par oposto" (the SPEC leaves them open), both checked on the sampled
queries with the truth table of the contrast:
- verified no effect: a factor f of D that is a true dummy on every sampled *changed* query, i.e.
  state_{S ∪ {f}} = state_S for every admissible S;
- opposing pair: factors f != g of D and a sampled query with state_{f} != state_∅ and state_{f,g} = state_∅
  (g undoes the isolated effect of f; cancellation, EX-08).
Shapes of a changed query follow its minimal family: unitary (one singleton set), several (two or more sets),
interaction (a set of size >= 2), nonmonotone (SPEC 6.1 flag).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, field

from habench.oracle import families as fam_mod
from habench.pipeline import catalog
from habench.pipeline.catalog import V1, V2
from habench.scenarios import patches as P
from habench.scenarios.base import Assessed, Candidate, Ctx, take
from habench.scenarios.families import entity_rows, others_pass, trait_ok
from habench.scenarios.levels import DEV_CAL_THRESHOLDS

SHAPES = ("unitary", "several", "interaction", "nonmonotone")


@dataclass
class ShapeQuota:
    """Minimum number of changed queries per shape, accumulated over the accepted X(ii) contrasts of a run."""

    target: dict[str, int]
    counts: Counter = field(default_factory=Counter)

    def open_shapes(self) -> set[str]:
        return {s for s in SHAPES if self.counts[s] < int(self.target.get(s, 0))}

    def wants(self, shapes: Counter) -> bool:
        """A contrast is accepted if it feeds an open shape, or when every quota is already filled."""
        opened = self.open_shapes()
        return not opened or any(shapes[s] for s in opened)

    def add(self, shapes: Counter) -> None:
        self.counts.update(shapes)


# ---------------------------------------------------------------------- X(i) and X(iii)


def x_bundle(ctx: Ctx) -> Iterator[Candidate]:
    note = (ctx.cfg.family("X")["i_note"],)
    c = ctx.candidate("X", "v1_to_v2_bundle", V1, V2, bundles={"V1_TO_V2": tuple(sorted(V1.diff(V2)))}, notes=note)
    if c:
        yield c


def x_components(ctx: Ctx) -> Iterator[Candidate]:
    c = ctx.candidate("X", "v1_to_v2_components", V1, V2, notes=(ctx.cfg.family("X")["i_note"],))
    if c:
        yield c


def x_ex07(ctx: Ctx) -> Iterator[Candidate]:
    """EX-07 shape: ent_thr lowered to or below an entity's es, icd_thr lowered, and a patch raising that es
    above the V1 threshold. The entity sits in [0.55, 0.60) so that the V1 threshold vetoes it in x0."""
    lo, hi = 0.55, float(V1["ent_thr"])
    rows = [(m, i, e) for m, i, e in entity_rows(ctx)
            if e.get("Score") is not None and lo <= e["Score"] < hi and trait_ok(e)
            and others_pass(ctx, "ent_thr", e)]
    ctx.rng("X", "iii").shuffle(rows)
    if not rows:
        ctx.report.drop("X", "no_ex07_entity")
    for m, i, _ in rows[:20]:
        try:
            p = P.set_entity_score(ctx.docs, m, i, hi + 0.02)
        except P.PatchError:
            continue
        c = ctx.candidate("X", "iii_ex07", V1, V1.with_(ent_thr=lo, icd_thr=0.55), patches=[p],
                          notes=("semisynthetic: SPEC 7.2 example (EX-07 shape), dev/cal only",))
        if c:
            yield c


# ---------------------------------------------------------------------- X(ii): drawing


def _raise_patch(ctx: Ctx, rng, factor: str, t0: float, t1: float, margin: float) -> P.Patch | None:
    """A patch raising a V1-passing score in [t0, t1) to t1 + margin: the opposing partner of a threshold raise."""
    rows = []
    for m, i, e in entity_rows(ctx):
        for j in others_pass(ctx, factor, e):
            score = e["Score"] if factor == "ent_thr" else e["ICD10CMConcepts"][j]["Score"]
            if score is not None and t0 <= score < t1:
                rows.append((m, i, None if factor == "ent_thr" else e["ICD10CMConcepts"][j]["Code"]))
            if factor == "ent_thr":
                break
    rng.shuffle(rows)
    value = round(min(1.0, t1 + margin), 6)
    for m, i, code in rows[:10]:
        try:
            return (P.set_entity_score(ctx.docs, m, i, value) if code is None
                    else P.set_concept_score(ctx.docs, m, i, code, value))
        except P.PatchError:
            continue
    return None


def _random_patch(ctx: Ctx, rng, existing: list[P.Patch]) -> P.Patch | None:
    rows = entity_rows(ctx)
    if not rows:
        return None
    for _ in range(10):
        m, i, e = rng.choice(rows)
        kind = rng.choice(["score", "negation", "remove_trait"])
        try:
            if kind == "score":
                p = P.set_entity_score(ctx.docs, m, i, round(rng.uniform(0.5, 0.95), 2))
            elif kind == "negation":
                p = P.add_trait(ctx.docs, m, i, "NEGATION", 0.8)
            else:
                names = sorted({t["Name"] for t in e.get("Traits") or [] if t.get("Name")})
                if not names:
                    continue
                p = P.remove_trait(ctx.docs, m, i, rng.choice(names))
            P.check_patches(ctx.docs, [*existing, p])
        except P.PatchError:
            continue
        return p
    return None


def _draw(ctx: Ctx, rng, X) -> Candidate | None:
    """One trial: a cancellation gadget (threshold raise + patch raising a score back) plus k - 2 more factors."""
    k = int(rng.choice(list(X["k"])))
    thr = rng.choice(["ent_thr", "icd_thr"])
    t0 = float(V1[thr])
    t1 = float(rng.choice([t for t in DEV_CAL_THRESHOLDS[thr] if t > t0]))
    gadget = _raise_patch(ctx, rng, thr, t0, t1, float(X["patch_value_margin"]))
    if gadget is None:
        ctx.report.drop("X", "no_cancellation_gadget")
        return None
    x1 = V1.with_(**{thr: t1})
    patches = [gadget]
    other = "icd_thr" if thr == "ent_thr" else "ent_thr"
    pool = [other, "trait", "occ", "sel", "map", "patch"]
    for slot in rng.sample(pool, k - 2):
        if slot == other:
            x1 = x1.with_(**{other: float(rng.choice([t for t in DEV_CAL_THRESHOLDS[other] if t != V1[other]]))})
        elif slot == "trait":
            x1 = x1.with_(trait=rng.choice([t for t in catalog.TRAIT_RULES if t != V1["trait"]]))
        elif slot == "occ":
            x1 = x1.with_(occ=rng.choice(["per_entity_any", "first_upsert"]))
        elif slot == "sel":
            x1 = x1.with_(sel="top1")
        elif slot == "map":
            dummy = rng.random() < float(X["dummy_map_probability"])
            x1 = x1.with_(map="who_exact_fb" if dummy else rng.choice(["who_exact", "who_cat3", "cm_ungated"]))
        else:
            p = _random_patch(ctx, rng, patches)
            if p is not None:
                patches.append(p)
    return ctx.candidate("X", "ii_sampled", V1, x1, space="who", patches=patches,
                         notes=("semisynthetic: rejection-sampled combination with a cancellation gadget",))


def _attempts(ctx: Ctx) -> Iterator[Candidate]:
    X = ctx.cfg.family("X")
    rng = ctx.rng("X", "ii")
    for _ in range(int(X["max_attempts"])):
        c = _draw(ctx, rng, X)
        if c is not None:
            yield c


# ---------------------------------------------------------------------- X(ii): acceptance


def query_shapes(D, table) -> set[str]:
    r = fam_mod.analyze(D, table)
    if not r.changed:
        return set()
    fam = r.family
    out = set()
    if len(fam) == 1 and all(len(S) == 1 for S in fam):
        out.add("unitary")
    if len(fam) >= 2:
        out.add("several")
    if any(len(S) >= 2 for S in fam):
        out.add("interaction")
    if r.nonmonotone:
        out.add("nonmonotone")
    return out


def is_dummy(f: str, table) -> bool:
    return all(table[S | {f}] == st for S, st in table.items() if f not in S and S | {f} in table)


def has_opposing_pair(D, tables) -> bool:
    empty = frozenset()
    for t in tables:
        for f in D:
            if t[frozenset({f})] == t[empty]:
                continue
            if any(t[frozenset({f, g})] == t[empty] for g in D if g != f):
                return True
    return False


def sample_x_ii(ctx: Ctx, quota: ShapeQuota, n: int) -> list[Assessed]:
    """Rejection sampling: up to `max_attempts` trials, accepting contrasts that meet the rules and the quota."""

    def accept(a: Assessed) -> bool:
        h, sc = a.hybrids, a.scenario
        if not 3 <= len(h.D) <= 6:
            ctx.report.drop("X", "k_out_of_range")
            return False
        changed = set(a.sample.changed)
        tables = {key: h.truth_table(key) for _, key in sc.queries}
        chg = [t for key, t in tables.items() if key in changed]
        if not any(all(is_dummy(f, t) for t in chg) for f in h.D):
            ctx.report.drop("X", "no_verified_no_effect_factor")
            return False
        if not has_opposing_pair(h.D, tables.values()):
            ctx.report.drop("X", "no_opposing_pair")
            return False
        shapes = Counter(s for t in chg for s in query_shapes(h.D, t))
        if not quota.wants(shapes):
            ctx.report.drop("X", "shape_quota_full")
            return False
        quota.add(shapes)
        return True

    out = take(ctx, _attempts(ctx), n, accept=accept)
    if len(out) < n:
        ctx.report.drop("X", "ii_below_target")
    return out
