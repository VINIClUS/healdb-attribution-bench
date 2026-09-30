"""Worked examples of docs/SPEC.md, checked by a self-contained brute-force reference.

The reference below does not import ``habench`` (only the vocabulary test does). Every expected answer is computed
from the example inputs in ``tests/data/spec_examples.json`` following the SPEC semantics; the JSON expectations are
only compared against, never copied into the code.
"""

import copy
import itertools
import json
import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent
DATA = json.loads((ROOT / "tests" / "data" / "spec_examples.json").read_text(encoding="utf-8"))
SPEC_TEXT = (ROOT / "docs" / "SPEC.md").read_text(encoding="utf-8")

CATS = frozenset(DATA["hierarchy"]["categories"])
SUBCATS = frozenset(DATA["hierarchy"]["subcategories"])
HIER_VERSION = DATA["hierarchy"]["version"]
PRESETS = DATA["presets"]
EXAMPLES = {e["id"]: e for e in DATA["examples"]}

CONFIG_FACTORS = ("occ", "sel", "ent_thr", "icd_thr", "trait", "map")
VETO_V1 = frozenset({"LOW_CONFIDENCE", "NEGATION", "PERTAINS_TO_FAMILY"})
DXS = frozenset({"DIAGNOSIS", "SYMPTOM", "SIGN"})

Fam = frozenset  # frozenset[frozenset[str]]

HANDLED_KINDS: set[str] = set()


def for_kind(kind: str) -> Callable:
    """Parametrize a test over every JSON example of `kind` (ids name the failing example)."""
    HANDLED_KINDS.add(kind)
    return pytest.mark.parametrize(
        "ex", [e for e in DATA["examples"] if e["kind"] == kind], ids=lambda e: e["id"]
    )


def fam(sets: Iterable[Iterable[str]]) -> Fam:
    return frozenset(frozenset(s) for s in sets)


# --------------------------------------------------------------------------------------------------------------
# SPEC 1: projections, keys, presence
# --------------------------------------------------------------------------------------------------------------


def project(level: str, code: str) -> str | None:
    nd = code.replace(".", "")
    if level == "cm_gated":
        return code if (nd in CATS or nd in SUBCATS or nd[:3] in CATS) else None
    if level == "cm_ungated":
        return code
    if level == "who_exact_fb":
        if nd in SUBCATS or nd in CATS:
            return nd
        return nd[:3] if nd[:3] in CATS else None
    if level == "who_exact":
        return nd if (nd in SUBCATS or nd in CATS) else None
    if level == "who_cat3":
        return nd[:3] if nd[:3] in CATS else None
    raise ValueError(level)


def space_key(level: str, code: str, space: str, ungated: bool = False) -> str | None:
    """Key code of `code` in the comparison space (SPEC 1.3); None when the map produces no key."""
    if level.startswith("cm_"):
        own = project("cm_ungated" if ungated else level, code)
        if own is None:
            return None
        return own if space == "CM" else project("who_exact_fb", code)
    if space == "CM":
        raise ValueError("CM space requires cm_* map levels")
    return project(level, code)


def assoc_key(med: int, space: str, code: str, model_version: str) -> tuple[int, str, str, str]:
    if space == "CM":
        return (med, "ICD-10-CM", f"acm:{model_version}", code)
    return (med, "ICD-10-WHO", HIER_VERSION, code)


# --------------------------------------------------------------------------------------------------------------
# SPEC 4.3: variants
# --------------------------------------------------------------------------------------------------------------


def normalize_variant(factor: str, level: Any, variant: str | None) -> str:
    """`alt` exists only for the (factor, level) pairs of SPEC 4.3; everything else is `std`."""
    if variant != "alt":
        return "std"
    if factor in ("ent_thr", "icd_thr"):
        return "alt"
    if factor == "trait" and level == "v1":
        return "alt"
    if factor == "occ" and level == "last_upsert":
        return "alt"
    if factor == "map" and level == "cm_gated":
        return "alt"
    return "std"


def resolve_cfg(spec: dict[str, Any]) -> dict[str, Any]:
    if "preset" not in spec:
        return dict(spec)
    cfg = dict(PRESETS[spec["preset"]])
    cfg.update({k: v for k, v in spec.items() if k != "preset"})
    return cfg


def norm_variants(cfg: dict[str, Any], variants: dict[str, str] | None) -> dict[str, str]:
    variants = variants or {}
    return {f: normalize_variant(f, cfg[f], variants.get(f)) for f in CONFIG_FACTORS}


# --------------------------------------------------------------------------------------------------------------
# SPEC 3: core (patches, candidates, sel, occ, predicates, trace)
# --------------------------------------------------------------------------------------------------------------


def apply_patches(evidence: dict[str, Any], ops: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """SPEC 4.5 operations on a deep copy of the response."""
    ev = copy.deepcopy(evidence)
    ents = ev["entities"]

    def find(eid: int) -> dict[str, Any]:
        return next(e for e in ents if e["id"] == eid)

    for op in ops:
        kind = op["op"]
        if kind == "set_entity_score":
            find(op["entity"])["score"] = op["value"]
        elif kind == "set_concept_score":
            for concept in find(op["entity"])["concepts"]:
                if concept[0] == op["code"]:
                    concept[1] = op["value"]
        elif kind == "add_trait":
            find(op["entity"])["traits"].append([op["name"], op["score"]])
        elif kind == "remove_trait":
            ent = find(op["entity"])
            ent["traits"] = [t for t in ent["traits"] if t[0] != op["name"]]
        elif kind == "swap_entities":
            ia = next(i for i, e in enumerate(ents) if e["id"] == op["a"])
            ib = next(i for i, e in enumerate(ents) if e["id"] == op["b"])
            ents[ia], ents[ib] = ents[ib], ents[ia]
        else:
            raise ValueError(kind)
    return ev


@dataclass(frozen=True)
class Cand:
    pos: int
    ent_index: int
    eid: int
    code: str
    rank: int
    es: float
    cs: float
    traits: tuple[tuple[str, float], ...]
    type: str


@dataclass(frozen=True)
class Rec:
    code: str
    key: str | None
    failed: frozenset[str]

    @property
    def verdict(self) -> str:
        return "fail" if self.failed else "pass"


def candidates(evidence: dict[str, Any]) -> list[Cand]:
    out: list[Cand] = []
    for ent_index, ent in enumerate(evidence["entities"]):
        ordered = sorted(ent["concepts"], key=lambda c: (-c[1], c[0]))
        rank_of = {c[0]: i + 1 for i, c in enumerate(ordered)}
        traits = tuple((n, s) for n, s in ent["traits"])
        for code, cs in ent["concepts"]:
            out.append(
                Cand(len(out), ent_index, ent["id"], code, rank_of[code], ent["score"], cs, traits, ent["type"])
            )
    return out


def trait_passes(level: str, variant: str, rtype: str, traits: dict[str, float]) -> bool:
    if level == "v2":
        return "NEGATION" not in traits and rtype == "DX_NAME"
    if level == "neg_only":
        return "NEGATION" not in traits
    hyp = traits.get("HYPOTHETICAL")
    veto_at = 0.60 if (level == "v1_hyp_le_0.6" or (level == "v1" and variant == "alt")) else 0.65
    if VETO_V1 & traits.keys():
        return False
    if hyp is not None and hyp > veto_at:
        return False
    if level == "v1_no_required":
        return True
    return bool(DXS & traits.keys()) or (hyp is not None and hyp <= 0.60)


def build_records(evidence: dict[str, Any], cfg: dict[str, Any], var: dict[str, str], space: str) -> list[Rec]:
    cands = candidates(evidence)
    occ = cfg["occ"]
    if cfg["sel"] == "top1":
        # per_entity_any: the "entity" is the group of entities with the same Id (SPEC 3.2 step 3).
        group = (lambda c: c.eid) if occ == "per_entity_any" else (lambda c: c.ent_index)
        best: dict[int, Cand] = {}
        for c in cands:
            g = group(c)
            if g not in best or (-c.cs, c.code) < (-best[g].cs, best[g].code):
                best[g] = c
        cands = [c for c in cands if best[group(c)] is c]
    if occ == "last_upsert" and var["occ"] == "alt":
        occ = "first_upsert"
    keyf = (lambda c: c.code) if occ != "per_entity_any" else (lambda c: (c.eid, c.code))
    groups: dict[Any, list[Cand]] = {}
    for c in cands:
        groups.setdefault(keyf(c), []).append(c)
    recs: list[Rec] = []
    for members in groups.values():
        first = occ == "first_upsert"
        pick = members[0] if first else members[-1]
        traits: dict[str, float] = {}
        for c in (reversed(members) if first else members):
            traits.update(dict(c.traits))
        failed: set[str] = set()
        if not trait_passes(cfg["trait"], var["trait"], pick.type, traits):
            failed.add("trait")
        ent_ok = pick.es > cfg["ent_thr"] if var["ent_thr"] == "alt" else pick.es >= cfg["ent_thr"]
        icd_ok = pick.cs > cfg["icd_thr"] if var["icd_thr"] == "alt" else pick.cs >= cfg["icd_thr"]
        if not ent_ok:
            failed.add("ent_thr")
        if not icd_ok:
            failed.add("icd_thr")
        key = space_key(cfg["map"], pick.code, space, ungated=(cfg["map"] == "cm_gated" and var["map"] == "alt"))
        if key is None:
            failed.add("map")
        recs.append(Rec(pick.code, key, frozenset(failed)))
    return recs


def presence(evidence: dict[str, Any] | None, cfg: dict[str, Any], var: dict[str, str], space: str, query: str) -> str:
    if evidence is None:
        return "unavailable"
    recs = build_records(evidence, cfg, var, space)
    return "present" if any(r.key == query and not r.failed for r in recs) else "absent"


def present_keys(evidence: dict[str, Any], cfg: dict[str, Any], space: str) -> list[str]:
    recs = build_records(evidence, cfg, norm_variants(cfg, None), space)
    return sorted({r.key for r in recs if r.key is not None and not r.failed})


# --------------------------------------------------------------------------------------------------------------
# SPEC 5/6: contrasts, hybrids, admissibility, minimal families
# --------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Contrast:
    evidence: dict[str, Any] | None
    x0: dict[str, Any]
    x1: dict[str, Any]
    var0: dict[str, str]
    var1: dict[str, str]
    space: str
    query: str
    factors: tuple[str, ...]
    patches: dict[str, list[dict[str, Any]]]
    bundles: dict[str, list[str]]
    prep_factors: tuple[str, ...]
    prep_responses: dict[str, Any] | None


def make_contrast(
    evidence: dict[str, Any] | None,
    x0: dict[str, Any],
    x1: dict[str, Any],
    space: str,
    query: str,
    factors: Sequence[str],
    var0: dict[str, str] | None = None,
    var1: dict[str, str] | None = None,
    patches: dict[str, list[dict[str, Any]]] | None = None,
    bundles: dict[str, list[str]] | None = None,
    prep: dict[str, Any] | None = None,
) -> Contrast:
    c0, c1 = resolve_cfg(x0), resolve_cfg(x1)
    return Contrast(
        evidence=evidence,
        x0=c0,
        x1=c1,
        var0=norm_variants(c0, var0),
        var1=norm_variants(c1, var1),
        space=space,
        query=query,
        factors=tuple(factors),
        patches=patches or {},
        bundles=bundles or {},
        prep_factors=tuple(prep["factors"]) if prep else (),
        prep_responses=prep["responses"] if prep else None,
    )


def subset_key(S: Iterable[str]) -> str:
    return ",".join(sorted(S))


def is_admissible(c: Contrast, S: frozenset[str]) -> bool:
    if c.prep_responses is None:
        return True
    return subset_key(f for f in S if f in c.prep_factors) in c.prep_responses


def hybrid_state(c: Contrast, S: frozenset[str]) -> str:
    cfg, var = dict(c.x0), dict(c.var0)
    evidence = c.evidence
    ops: list[dict[str, Any]] = []
    for f in sorted(S):
        for comp in c.bundles.get(f, [f] if f in CONFIG_FACTORS else []):
            cfg[comp], var[comp] = c.x1[comp], c.var1[comp]
        ops += c.patches.get(f, [])
    if c.prep_responses is not None:
        evidence = c.prep_responses[subset_key(f for f in S if f in c.prep_factors)]
    if evidence is not None:
        evidence = apply_patches(evidence, ops)
    return presence(evidence, cfg, var, c.space, c.query)


def all_subsets(D: Iterable[str]) -> list[frozenset[str]]:
    names = sorted(D)
    return [frozenset(s) for k in range(len(names) + 1) for s in itertools.combinations(names, k)]


@dataclass(frozen=True)
class Analysis:
    D: frozenset[str]
    states: dict[frozenset[str], str]  # admissible subsets only
    changed: bool
    sufficient: frozenset[frozenset[str]]
    family: Fam | None
    complete: bool | None
    nonmonotone: bool | None


def analyze(c: Contrast) -> Analysis:
    D = frozenset(c.factors)
    subs = all_subsets(D)
    adm = {S for S in subs if is_admissible(c, S)}
    states = {S: hybrid_state(c, S) for S in subs if S in adm}
    empty = frozenset()
    if states[empty] == states[D]:
        return Analysis(D, states, False, frozenset(), None, None, None)
    target = states[D]
    suff = {S for S in adm if states[S] == target}
    # SPEC 6.2 dynamic programme: sub[S] = suff[S] or any sub[S - i]; minimal[S] = suff[S] and not any sub[S - i].
    sub: dict[frozenset[str], bool] = {}
    minimal: set[frozenset[str]] = set()
    for S in subs:  # ordered by size
        below = any(sub[S - {i}] for i in S)
        sub[S] = S in suff or below
        if S in suff and not below:
            minimal.add(S)
    # Naive O(3^n) cross-check (SPEC 6.2, property tests).
    naive = {S for S in suff if not any(T < S and T in suff for T in adm)}
    assert minimal == naive
    complete = all(any(T < S and T in suff for T in adm) for S in subs if S not in adm)
    nonmono = any(T > S and T in adm and T not in suff for S in suff for T in subs)
    return Analysis(D, states, True, frozenset(suff), frozenset(minimal), complete, nonmono)


# SPEC 6.3 reference BFS ---------------------------------------------------------------------------------------


def reference_bfs(
    D: Sequence[str],
    is_sufficient: Callable[[frozenset[str]], bool],
    budget: int | None,
    is_admissible_fn: Callable[[frozenset[str]], bool] = lambda S: True,
    dummy: frozenset[str] = frozenset(),
) -> tuple[list[frozenset[str]], Fam, bool]:
    names = sorted(D)
    full = frozenset(names)
    evaluated: list[frozenset[str]] = []
    found: list[frozenset[str]] = []
    exhausted = False

    def spend(S: frozenset[str]) -> bool | None:
        if budget is not None and len(evaluated) >= budget:
            return None
        evaluated.append(S)
        return is_sufficient(S)

    spend(frozenset())
    spend(full)
    for k in range(1, len(names)):
        for combo in itertools.combinations(names, k):
            S = frozenset(combo)
            if any(T <= S for T in found) or (S & dummy) or not is_admissible_fn(S):
                continue
            verdict = spend(S)
            if verdict is None:
                exhausted = True
                break
            if verdict:
                found.append(S)
        if exhausted:
            break
    family = set(found)
    if not exhausted and not any(T <= full for T in found):
        family.add(full)
    return evaluated, frozenset(family), not exhausted


# SPEC 4.6 dummy certificates -----------------------------------------------------------------------------------


def dummy_certificate(c: Contrast, f: str) -> bool | None:
    """Reference rules 1-4; None when undecided."""
    if any(p in c.factors for p in c.patches) or f not in CONFIG_FACTORS or f in c.bundles:
        return None
    maps = {c.x0["map"], c.x1["map"]}
    cands = [
        cand
        for cand in candidates(c.evidence or {"entities": []})
        if any(space_key(m, cand.code, c.space) == c.query for m in maps)
    ]
    if f in ("ent_thr", "icd_thr"):
        if c.var0[f] != "std" or c.var1[f] != "std":
            return None
        lo, hi = sorted((c.x0[f], c.x1[f]))
        attr = "es" if f == "ent_thr" else "cs"
        return True if not any(lo <= getattr(cand, attr) < hi for cand in cands) else None
    if f == "sel":
        return True if all(cand.rank == 1 for cand in cands) else None
    if f == "occ":
        by_code: dict[str, set[int]] = {}
        counts: dict[str, int] = {}
        for cand in cands:
            by_code.setdefault(cand.code, set()).add(cand.eid)
            counts[cand.code] = counts.get(cand.code, 0) + 1
        return True if all(n == 1 and len(by_code[k]) == 1 for k, n in counts.items()) else None
    if f == "map":
        both = {c.x0["map"], c.x1["map"]}
        return True if (both == {"cm_gated", "who_exact_fb"} and c.space == "WHO") else None
    return None


def truly_dummy(c: Contrast, f: str) -> bool:
    D = frozenset(c.factors)
    return all(
        hybrid_state(c, S | {f}) == hybrid_state(c, S) for S in all_subsets(D - {f})
    )


# --------------------------------------------------------------------------------------------------------------
# SPEC 8.1: observation and W
# --------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class History:
    evidence: dict[str, Any]
    x0: dict[str, Any]
    x1: dict[str, Any]
    var0: dict[str, str]
    var1: dict[str, str]


def universe_histories(universe: dict[str, Any]) -> dict[tuple[int, int, int], History]:
    out: dict[tuple[int, int, int], History] = {}
    for (i, ev), (j, ex), (k, va) in itertools.product(
        enumerate(universe["evidence"]), enumerate(universe["executed"]), enumerate(universe["variants"])
    ):
        out[(i, j, k)] = History(ev, resolve_cfg(ex["x0"]), resolve_cfg(ex["x1"]), va["x0"], va["x1"])
    return out


def executed_diff(h: History) -> list[str]:
    v0, v1 = norm_variants(h.x0, h.var0), norm_variants(h.x1, h.var1)
    return [f for f in CONFIG_FACTORS if (h.x0[f], v0[f]) != (h.x1[f], v1[f])]


def history_contrast(h: History, space: str, query: str) -> Contrast:
    return make_contrast(h.evidence, h.x0, h.x1, space, query, executed_diff(h), h.var0, h.var1)


def history_family(h: History, space: str, query: str) -> Fam | None:
    return analyze(history_contrast(h, space, query)).family


def replay(h: History, declared: dict[str, Any], link: bool, space: str, query: str) -> dict[str, str]:
    """SPEC 5.4: executed levels with the code link, declared levels without; each level keeps its run's variant."""
    x0 = h.x0 if link else resolve_cfg(declared["x0"])
    x1 = h.x1 if link else resolve_cfg(declared["x1"])
    d_vis = [f for f in CONFIG_FACTORS if x0[f] != x1[f]]
    c = make_contrast(h.evidence, x0, x1, space, query, d_vis, h.var0, h.var1)
    return {subset_key(S): hybrid_state(c, S) for S in all_subsets(d_vis)}


def trace_of(evidence: dict[str, Any], cfg: dict[str, Any], var: dict[str, str], maps: set[str], space: str, query: str):
    recs = build_records(evidence, cfg, var, space)
    return tuple(
        (r.verdict, tuple(sorted(r.failed)))
        for r in recs
        if any(space_key(m, r.code, space) == query for m in maps)
    )


VIEW_FLAGS = {  # (evidence, code_link, trace)
    "L1": (False, False, False),
    "L2-R": (True, True, False),
    "L2-M": (True, True, True),
    "L2-R-A3": (True, False, False),
}


def observation(h: History, view: str, capability: str, declared: dict[str, Any], space: str, query: str):
    with_evidence, link, with_trace = VIEW_FLAGS[view]
    truth = analyze(history_contrast(h, space, query))
    obs: list[Any] = [
        ("finals", truth.states[frozenset()], truth.states[truth.D]),
        ("hashes", True),  # E0 == E1 in every universe of the examples
    ]
    if with_evidence:
        obs.append(("evidence", json.dumps(h.evidence, sort_keys=True)))
    if link:
        obs.append(("levels", tuple(sorted(h.x0.items())), tuple(sorted(h.x1.items()))))
    if with_trace:
        maps = {h.x0["map"], h.x1["map"]}
        v0, v1 = norm_variants(h.x0, h.var0), norm_variants(h.x1, h.var1)
        obs.append(
            (
                "trace",
                trace_of(h.evidence, h.x0, v0, maps, space, query),
                trace_of(h.evidence, h.x1, v1, maps, space, query),
            )
        )
    if capability == "R-A":
        obs.append(("replay", tuple(sorted(replay(h, declared, link, space, query).items()))))
    return tuple(obs)


def identification_set(ex: dict[str, Any], view: str, capability: str) -> tuple[set, dict[tuple, Any]]:
    histories = universe_histories(ex["universe"])
    t = ex["true"]
    true_h = histories[(t["evidence"], t["executed"], t["variants"])]
    args = (ex["declared"], ex["space"], ex["query"])
    target = observation(true_h, view, capability, *args)
    w = {
        history_family(h, ex["space"], ex["query"])
        for h in histories.values()
        if observation(h, view, capability, *args) == target
    }
    return w, histories


# --------------------------------------------------------------------------------------------------------------
# SPEC 9: output validation, backing, scoring
# --------------------------------------------------------------------------------------------------------------


def family_is_valid(f: Fam) -> bool:
    if not f or any(len(s) == 0 for s in f):
        return False
    return not any(a < b for a in f for b in f)


def output_is_valid(state: str, families: Sequence[Sequence[Sequence[str]]]) -> bool:
    fams = [fam(f) for f in families]
    if state == "explicacao_verificada":
        return len(fams) == 1 and family_is_valid(fams[0])
    if state == "alternativas":
        return len(set(fams)) >= 2 and len(set(fams)) == len(fams) and all(family_is_valid(f) for f in fams)
    return not fams


def backing_check(
    D: frozenset[str],
    truth_sufficient: frozenset[frozenset[str]],
    certificates: Sequence[dict[str, Any]],
    states: dict[frozenset[str], str],
) -> tuple[bool, bool]:
    """Returns (all certificates true, coverage) per SPEC 9.2."""
    all_true = True
    certified: dict[frozenset[str], bool] = {}
    dummies: set[str] = set()
    for cert in certificates:
        S = frozenset(cert["subject"]) & D
        if cert["kind"] == "dummy":
            (f,) = S
            is_dummy = all(states[T | {f}] == states[T] for T in all_subsets(D - {f}))
            all_true &= is_dummy == cert["value"]
            if cert["value"]:
                dummies |= S
            continue
        all_true &= (S in truth_sufficient) == cert["value"]
        certified[S] = cert["value"]
    cert_suff = [S for S, v in certified.items() if v]
    covered = all(
        S in certified or any(T < S for T in cert_suff) or bool(S & dummies) for S in all_subsets(D)
    )
    return all_true, covered


CELLS = ("identificado", "ambiguo", "indeterminado", "incompleta", "inalterado")
OUTCOMES = frozenset(
    {
        "correto_sustentado",
        "errado",
        "indevidamente_exclusivo",
        "nao_comprometido",
        "abstencao_apropriada",
        "abstencao_desnecessaria",
        "falha",
        "excluido",
    }
)


def score(
    cell: str,
    state: str,
    families: Sequence[Sequence[Sequence[str]]],
    backed: bool,
    certs_true: bool,
    F_star: Fam | None,
    W_lo: frozenset[Fam] | None,
    W_hi: frozenset[Fam] | None,
    F_adm: Fam | None,
    needed: int,
    budget: int,
) -> str:
    """SPEC 9.3. Precedence: errado > indevidamente exclusivo > nao comprometido > correto sustentado."""
    if state == "falha_de_execucao":
        return "falha"
    if cell == "indeterminado":
        return "excluido"
    if state == "explicacao_verificada":
        F = fam(families[0])
        if not certs_true:
            return "errado"
        if cell == "identificado":
            if F != F_star:
                return "errado"
            return "correto_sustentado" if backed else "indevidamente_exclusivo"
        if cell == "ambiguo":
            return "indevidamente_exclusivo" if F == F_star else "errado"
        if cell == "incompleta":
            return "indevidamente_exclusivo" if F == F_adm else "errado"
        return "errado"  # inalterado
    if state == "alternativas":
        A = frozenset(fam(f) for f in families)
        if cell == "identificado":
            return "nao_comprometido" if F_star in A else "errado"
        if cell == "ambiguo":
            if F_star not in A:
                return "errado"
            if not W_lo <= A:
                return "indevidamente_exclusivo"
            return "correto_sustentado" if A <= W_hi else "nao_comprometido"
        if cell == "incompleta":
            return "nao_comprometido" if F_adm in A else "errado"
        return "errado"  # inalterado
    changed = cell in ("identificado", "ambiguo", "incompleta")
    if state == "ausencia_de_mudanca":
        return "errado" if changed else "correto_sustentado"
    if state == "compativel_com_variabilidade":
        return "errado" if changed else "nao_comprometido"
    if cell == "inalterado":
        return "abstencao_desnecessaria"
    if state == "informacao_insuficiente":
        return "abstencao_apropriada" if cell in ("ambiguo", "incompleta") else "abstencao_desnecessaria"
    if state == "contrafactual_indisponivel":
        return "abstencao_apropriada" if cell == "incompleta" else "abstencao_desnecessaria"
    if state == "orcamento_esgotado":
        return "abstencao_apropriada" if needed > budget else "abstencao_desnecessaria"
    raise ValueError(state)


# --------------------------------------------------------------------------------------------------------------
# SPEC 10 and 13: metrics and statistics
# --------------------------------------------------------------------------------------------------------------

CATEGORICAL_STATES = frozenset(
    {"explicacao_verificada", "alternativas", "ausencia_de_mudanca", "compativel_com_variabilidade"}
)


def compute_metrics(queries: Sequence[dict[str, Any]]) -> dict[str, float]:
    q_c = [q for q in queries if q["cell"] in ("identificado", "ambiguo")]
    q_inc = [q for q in queries if q["cell"] == "incompleta"]
    q_ind = [q for q in queries if q["cell"] == "indeterminado"]
    q_u = [q for q in queries if q["cell"] == "inalterado"]

    def false_attribution(q: dict[str, Any]) -> bool:
        return q["state"] in ("explicacao_verificada", "alternativas")

    cat = [q for q in q_c + q_inc if q["state"] in CATEGORICAL_STATES]
    bad = [q for q in cat if q["outcome"] in ("errado", "indevidamente_exclusivo")]
    null_q = [q for q in q_u if q["family"] == "N"]
    null_contrasts = sorted({q["contrast"] for q in queries if q["family"] == "N"})
    null_groups = sorted({q["group"] for q in queries if q["family"] == "N"})
    false_null = [q for q in null_q if false_attribution(q)]
    return {
        "cobertura": sum(q["outcome"] == "correto_sustentado" for q in q_c) / len(q_c),
        "cobertura_bruta": sum(q["state"] in CATEGORICAL_STATES for q in q_c) / len(q_c),
        "risco_seletivo": len(bad) / len(cat),
        "null_group_rate": len({q["group"] for q in false_null}) / len(null_groups),
        "null_false_attributions_per_contrast": len(false_null) / len(null_contrasts),
        "unchanged_coverage": sum(q["outcome"] == "correto_sustentado" for q in q_u) / len(q_u),
        "unchanged_false_attribution_rate": sum(false_attribution(q) for q in q_u) / len(q_u),
        "falha_rate": sum(q["outcome"] == "falha" for q in q_c) / len(q_c),
        "n_indeterminado": len(q_ind),
        "n_incompleta": len(q_inc),
    }


def holm_reject(p: Sequence[float], alpha: float) -> list[bool]:
    m = len(p)
    order = sorted(range(m), key=lambda i: p[i])
    reject = [False] * m
    for rank, i in enumerate(order):
        if p[i] <= alpha / (m - rank):
            reject[i] = True
        else:
            break
    return reject


def ni_pvalue(deltas: Sequence[float], margin: float) -> float:
    return (1 + sum(d <= margin for d in deltas)) / (len(deltas) + 1)


# --------------------------------------------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------------------------------------------


def test_spec_and_json_have_the_same_example_ids() -> None:
    in_spec = set(re.findall(r"\bEX-S?\d{2}\b", SPEC_TEXT))
    in_json = {e["id"] for e in DATA["examples"]}
    assert len(in_json) == len(DATA["examples"]), "duplicate ids in the JSON"
    assert in_spec - in_json == set(), "ids in SPEC but not in JSON"
    assert in_json - in_spec == set(), "ids in JSON but not in SPEC"


def test_every_json_kind_is_handled() -> None:
    kinds = {e["kind"] for e in DATA["examples"]}
    assert kinds <= HANDLED_KINDS
    assert HANDLED_KINDS <= kinds, "a handler without examples"
    assert set(DATA["_schema"]["kinds"].split(", ")) == kinds


def test_output_state_vocabulary() -> None:
    from habench.types import OutputState

    values = {s.value for s in OutputState}
    used: set[str] = set()
    for e in DATA["examples"]:
        if e["kind"] == "scoring":
            used.add(e["output"]["state"])
        elif e["kind"] == "output_validation":
            used |= {c["state"] for c in e["cases"]}
        elif e["kind"] == "metrics":
            used |= {q["state"] for q in e["queries"]}
    assert used <= values, used - values
    assert values == set(CATEGORICAL_STATES) | {
        "informacao_insuficiente",
        "orcamento_esgotado",
        "contrafactual_indisponivel",
        "falha_de_execucao",
    }


@for_kind("projection")
def test_projection_and_keys(ex: dict[str, Any]) -> None:
    for case in ex["cases"]:
        assert project(case["map"], case["code"]) == case["expected"], case
    for k in ex["keys"]:
        got = assoc_key(k["med"], k["space"], k["code"], k["model_version"])
        assert list(got) == k["expected"]


@for_kind("presence")
def test_presence_and_eligibility(ex: dict[str, Any]) -> None:
    cfg = resolve_cfg(ex["config"])
    var = norm_variants(cfg, None)
    states = {
        run: presence(ex[run]["response"], cfg, var, ex["space"], ex["query"]) for run in ("x0", "x1")
    }
    eligible = all(s in ("present", "absent") for s in states.values())
    assert states == {"x0": ex["expected"]["x0"], "x1": ex["expected"]["x1"]}
    assert eligible == ex["expected"]["eligible"]


def content_form(raw: str) -> str:
    obj = json.loads(raw)
    obj.pop("ResponseMetadata", None)  # top-level key only (SPEC 2)
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


@for_kind("equality")
def test_raw_and_content_equality(ex: dict[str, Any]) -> None:
    for case in ex["cases"]:
        got = {"raw": ex["base"] == case["other"], "content": content_form(ex["base"]) == content_form(case["other"])}
        assert got == case["expected"], case["name"]


@for_kind("run")
def test_run_present_keys(ex: dict[str, Any]) -> None:
    for case in ex["cases"]:
        cfg = resolve_cfg(case["config"])
        assert present_keys(ex["evidence"], cfg, case["space"]) == sorted(case["expected_present"]), case["config"]


@for_kind("trait_rules")
def test_trait_rules_table(ex: dict[str, Any]) -> None:
    for row in ex["rows"]:
        entity = dict(ex["entity"], type=row["type"], traits=row["traits"])
        evidence = {"model_version": "3.0.0.20231001", "entities": [entity]}
        got = []
        for rule in ex["rules"]:
            cfg = resolve_cfg({**ex["config"], "trait": rule["trait"]})
            var = norm_variants(cfg, rule.get("variants"))
            state = presence(evidence, cfg, var, ex["space"], "C61")
            got.append("P" if state == "present" else "R")
        assert got == row["expected"], row


def contrast_from_family_example(ex: dict[str, Any], factors: Sequence[str], bundles: dict | None = None) -> Contrast:
    prep = ex.get("prep")
    evidence = prep["responses"][""] if prep else ex["evidence"]
    return make_contrast(
        evidence, ex["x0"], ex["x1"], ex["space"], ex["query"], factors,
        patches=ex.get("patches"), bundles=bundles, prep=prep,
    )


def check_family(a: Analysis, expected: dict[str, Any]) -> None:
    assert a.changed == expected["changed"]
    assert (None if a.family is None else {tuple(sorted(s)) for s in a.family}) == (
        None if expected["family"] is None else {tuple(sorted(s)) for s in expected["family"]}
    )
    assert a.nonmonotone == expected["nonmonotone"]
    assert a.complete == expected["complete"]
    if "sufficient" in expected:
        assert a.sufficient == fam(expected["sufficient"])
    if "states" in expected:
        for key, state in expected["states"].items():
            assert a.states[frozenset(filter(None, key.split(",")))] == state, key


@for_kind("family")
def test_minimal_family(ex: dict[str, Any]) -> None:
    if "granularities" in ex:
        for g in ex["granularities"]:
            c = contrast_from_family_example(ex, g["factors"], g.get("bundles"))
            check_family(analyze(c), g["expected"])
        return
    check_family(analyze(contrast_from_family_example(ex, ex["factors"])), ex["expected"])


@for_kind("dummy")
def test_dummy_certificates_and_truth(ex: dict[str, Any]) -> None:
    c = make_contrast(ex["evidence"], ex["x0"], ex["x1"], ex["space"], ex["query"], ex["factors"])
    certified = sorted(f for f in ex["factors"] if dummy_certificate(c, f) is True)
    truly = sorted(f for f in ex["factors"] if truly_dummy(c, f))
    assert certified == sorted(ex["expected"]["certified"])
    assert truly == sorted(ex["expected"]["truly_dummy"])
    assert set(certified) <= set(truly), "a certificate must never be false"
    assert dummy_certificate(c, "trait") is None and dummy_certificate(c, "occ") is None


@for_kind("bfs")
def test_reference_bfs(ex: dict[str, Any]) -> None:
    sufficient = {frozenset(s) for s in ex["sufficient"]}
    for case in ex["cases"]:
        evaluated, family, complete = reference_bfs(ex["D"], lambda S: S in sufficient, case["budget"])
        exp = case["expected"]
        assert len(evaluated) == exp["evaluations"]
        assert family == fam(exp["family"])
        assert complete == exp["complete"]
        if "evaluated_order" in exp:
            assert [sorted(S) for S in evaluated] == exp["evaluated_order"]


@for_kind("identification")
def test_identification_sets(ex: dict[str, Any]) -> None:
    histories = None
    for v in ex["views"]:
        w, histories = identification_set(ex, v["view"], v["capability"])
        assert w == {fam(f) for f in v["expected_families"]}, (v["view"], v["capability"])
    t = ex["true"]
    true_h = histories[(t["evidence"], t["executed"], t["variants"])]
    assert history_family(true_h, ex["space"], ex["query"]) == fam(ex["expected_true_family"])
    key = "expected_replay_L2-R-A3_R-A"
    if key in ex:
        assert replay(true_h, ex["declared"], False, ex["space"], ex["query"]) == ex[key]
    if "witness" in ex:
        wit = ex["witness"]
        wh = histories[(wit["evidence"], wit["executed"], wit["variants"])]
        assert history_family(wh, ex["space"], ex["query"]) == fam(wit["family"])
        args = (ex["declared"], ex["space"], ex["query"])
        assert observation(wh, "L1", "R-C", *args) == observation(true_h, "L1", "R-C", *args)
        assert observation(wh, "L2-R", "R-C", *args) != observation(true_h, "L2-R", "R-C", *args)


@for_kind("backing")
def test_backing_certificates(ex: dict[str, Any]) -> None:
    source = EXAMPLES[ex["truth_from"]]
    a = analyze(contrast_from_family_example(source, source["factors"]))
    assert a.family == fam(ex["claimed_family"])
    for case in ex["cases"]:
        all_true, covered = backing_check(a.D, a.sufficient, case["certificates"], a.states)
        assert {"all_true": all_true, "covered": covered} == case["expected"], case["name"]


@for_kind("profiles")
def test_profile_chain_and_ablations(ex: dict[str, Any]) -> None:
    profiles = {k: set(v) for k, v in ex["profiles"].items()}
    chain = ex["chain"]
    strict = all(profiles[a] < profiles[b] for a, b in zip(chain, chain[1:]))
    removes_one = True
    for spec in ex["ablations"].values():
        for base in spec["bases"]:
            ablated = (profiles[base] - {spec["remove"]}) | ({spec["add"]} if spec["add"] else set())
            removes_one &= spec["remove"] in profiles[base] and len(profiles[base] - ablated) == 1
    combined_ok = all(set(parts) <= set(ex["ablations"]) for parts in ex["combined"].values())
    assert {
        "strict_chain": strict,
        "each_ablation_removes_one_present_item": removes_one,
        "combined_are_known_ablations": combined_ok,
    } == ex["expected"]


@for_kind("output_validation")
def test_output_validation(ex: dict[str, Any]) -> None:
    for case in ex["cases"]:
        assert output_is_valid(case["state"], case["families"]) == case["expected_valid"], case


def optional_fam(x: Any) -> Fam | None:
    return None if x is None else fam(x)


@for_kind("scoring")
def test_scoring_example(ex: dict[str, Any]) -> None:
    out = ex["output"]
    got = score(
        ex["cell"], out["state"], out["families"], out["backed"], out["certificates_true"],
        optional_fam(ex["F_star"]),
        None if ex["W_lo"] is None else frozenset(fam(f) for f in ex["W_lo"]),
        None if ex["W_hi"] is None else frozenset(fam(f) for f in ex["W_hi"]),
        optional_fam(ex["F_adm"]), ex["needed"], ex["budget"],
    )
    assert got == ex["expected"]


def test_scoring_table_is_total() -> None:
    from habench.types import OutputState

    f1, f2, f3 = [["ent_thr"]], [["ent_thr", "trait"]], [["trait"]]
    for cell in CELLS:
        star = fam(f1) if cell in ("identificado", "ambiguo", "indeterminado") else None
        w_lo = frozenset({fam(f1), fam(f2)}) if cell != "incompleta" and cell != "inalterado" else None
        w_hi = w_lo
        adm = fam([["ent_thr"], ["dup_ind", "mask_drug"]]) if cell == "incompleta" else None
        for state in OutputState:
            families = {
                "explicacao_verificada": [f1],
                "alternativas": [f1, f2],
            }.get(state.value, [])
            for backed, certs, budget in itertools.product((True, False), (True, False), (4, 64)):
                out = score(cell, state.value, families, backed, certs, star, w_lo, w_hi, adm, 6, budget)
                assert out in OUTCOMES, (cell, state)


@for_kind("metrics")
def test_metrics(ex: dict[str, Any]) -> None:
    got = compute_metrics(ex["queries"])
    assert set(got) == set(ex["expected"])
    for name, value in ex["expected"].items():
        assert got[name] == pytest.approx(value), name


@for_kind("holm")
def test_holm(ex: dict[str, Any]) -> None:
    for case in ex["cases"]:
        assert holm_reject(case["p"], ex["alpha"]) == case["expected_reject"], case["p"]


@for_kind("zero_event")
def test_zero_event_upper_bound(ex: dict[str, Any]) -> None:
    upper = 1 - ex["alpha"] ** (1 / ex["n"])
    assert upper == pytest.approx(ex["expected_upper"], abs=ex["tol"])


@for_kind("ni_pvalue")
def test_ni_pvalue(ex: dict[str, Any]) -> None:
    for case in ex["cases"]:
        p = ni_pvalue(case["deltas"], ex["margin"])
        assert p == pytest.approx(case["expected_p"])
        assert (p <= ex["alpha"]) == case["expected_reject"]
