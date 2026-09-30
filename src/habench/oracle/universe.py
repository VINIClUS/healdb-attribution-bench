"""Declared identification universe U (SPEC 8.2) and its expansion.

Two parts:
- **Hypotheses** on the executed levels and variants (SPEC 4.3): each (factor, run) may deviate from the
  declared (level, std) by an `alt` variant or, without the code link, by the paired level; at most
  `MAX_DEVIATIONS` deviations per history.
- **Bundles** of a's candidates (SPEC 8.2): an ordered sequence of up to `L` concept symbols partitioned
  into entities. Entity symbol = (es value, trait class, type, competitor flag); concept symbol = (cs value,
  code). Score values are one representative per band cut at the threshold levels (with the level itself,
  for the `>` variant); trait classes and codes are merged by behaviour. A competitor is a non-`a` concept
  with a higher cs in the same entity, so no `a` concept of that entity wins `top1`.

Bundles are evaluated in batches: each bundle becomes one synthetic medication of one `Evidence`, and the
core runs once per realized hybrid config for the whole batch. The expansion grows by one concept per
level from class representatives and stops at `L` or at the per-query budget; any cut means not saturated.

Declared simplifications (reported with the results): distinct entity Ids inside a bundle, and trait
classes merged by single-entity behaviour.
"""

from __future__ import annotations

import itertools
import json
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from habench.oracle.contrast import has_alt
from habench.oracle.families import analyze
from habench.oracle.hybrids import all_subsets, realize
from habench.pipeline import catalog, core, mapping
from habench.pipeline.catalog import Config
from habench.pipeline.evidence import Evidence
from habench.pipeline.mapping import Hierarchy
from habench.types import SYSTEM_ICD10_WHO, SYSTEM_ICD10CM, AssocKey, Family, Presence

MAX_DEVIATIONS = 3
L_MAX = 4
PAIR = {
    "trait": {"v1": "v1_hyp_le_0.6", "v1_hyp_le_0.6": "v1"},
    "occ": {"last_upsert": "first_upsert", "first_upsert": "last_upsert"},
    "map": {"cm_gated": "cm_ungated", "cm_ungated": "cm_gated"},
}
MODEL_VERSION = "3.0.0.20231001"


# ---------------------------------------------------------------------- hypotheses (SPEC 4.3)


@dataclass(frozen=True)
class Hypothesis:
    x0: Config  # executed levels (unrealized)
    x1: Config
    variants0: frozenset[str]
    variants1: frozenset[str]
    deviations: tuple[tuple[str, int, str], ...]  # (factor, run, "alt"|"pair")

    def realized(self, run: int, S_components: frozenset[str] | None = None) -> Config:
        """Realized config of run `run`; with `S_components`, the hybrid taking those factors from x1."""
        out = {}
        for f, lv0 in self.x0.items:
            if f.startswith("patch:"):
                continue
            src = 1 if (S_components is not None and f in S_components) or (S_components is None and run) else 0
            lv = self.x1[f] if src else lv0
            var = "alt" if f in (self.variants1 if src else self.variants0) else "std"
            out[f] = realize(f, lv, var)
        return Config.of(out)

    def D(self) -> frozenset[str]:
        a, b = self.x0.as_dict(), self.x1.as_dict()
        return frozenset(f for f in a if (a[f], f in self.variants0) != (b[f], f in self.variants1))


def hypotheses(d0: Config, d1: Config, *, code_link: bool, max_dev: int = MAX_DEVIATIONS,
               true: tuple[Config, Config, frozenset[str], frozenset[str]] | None = None) -> list[Hypothesis]:
    """Every history hypothesis with at most `max_dev` deviations from the declared (level, std).

    With the code link the executed levels are observed, so only variants deviate and the base levels are
    the true executed ones (`true`)."""
    b0, b1 = (true[0], true[1]) if (code_link and true) else (d0, d1)
    options: list[tuple[str, int, str]] = []
    for run, base in ((0, b0), (1, b1)):
        for f, lv in base.items:
            if f.startswith("patch:"):
                continue
            if has_alt(f, lv):
                options.append((f, run, "alt"))
            if not code_link and lv in PAIR.get(f, {}):
                options.append((f, run, "pair"))
    out = []
    for k in range(max_dev + 1):
        for devs in itertools.combinations(options, k):
            if len({(f, r) for f, r, _ in devs}) < len(devs):
                continue  # one deviation per (factor, run)
            x = [b0.as_dict(), b1.as_dict()]
            var: list[set[str]] = [set(), set()]
            for f, r, kind in devs:
                if kind == "pair":
                    x[r][f] = PAIR[f][x[r][f]]
                else:
                    var[r].add(f)
            ok = all(has_alt(f, x[r][f]) for r in (0, 1) for f in var[r])
            if ok:
                out.append(Hypothesis(Config.of(x[0]), Config.of(x[1]), frozenset(var[0]), frozenset(var[1]),
                                      tuple(devs)))
    return out


# ---------------------------------------------------------------------- alphabet (SPEC 8.2)


def _band_values(cuts: Iterable[float]) -> list[float]:
    cs = sorted(set(round(float(c), 6) for c in cuts))
    vals = [max(0.0, cs[0] - 0.02)]
    for i, c in enumerate(cs):
        vals.append(c)
        vals.append(round((c + cs[i + 1]) / 2, 6) if i + 1 < len(cs) else min(1.0, c + 0.02))
    return vals


TRAIT_NAMES = ("NEGATION", "LOW_CONFIDENCE", "PERTAINS_TO_FAMILY")
HYP_VALUES = (None, 0.55, 0.62, 0.7)
TYPES = ("DX_NAME", "SYSTEM_ORGAN_SITE")


def _trait_rule_pass(level: str, traits: dict[str, float], tp: str) -> bool:
    r = catalog.TRAIT_RULES[level]
    names = set(traits)
    if r.veto & names:
        return False
    hyp = traits.get("HYPOTHETICAL")
    if r.hyp_veto_gt is not None and hyp is not None and hyp > r.hyp_veto_gt:
        return False
    if r.required is not None and not (r.required & names or (hyp is not None and hyp <= r.hyp_ok_le)):
        return False
    return r.entity_type is None or tp == r.entity_type


def trait_classes(levels: Iterable[str]) -> list[tuple[tuple[tuple[str, float], ...], str]]:
    """One (traits, type) representative per behaviour vector over the trait levels in play."""
    levels = sorted(set(levels))
    seen: dict[tuple, tuple] = {}
    for bits in itertools.product((0, 1), repeat=len(TRAIT_NAMES)):
        for hyp in HYP_VALUES:
            for dxs in (0, 1):
                for tp in TYPES:
                    traits = {n: 0.9 for n, b in zip(TRAIT_NAMES, bits) if b}
                    if hyp is not None:
                        traits["HYPOTHETICAL"] = hyp
                    if dxs:
                        traits["DIAGNOSIS"] = 0.9
                    sig = tuple(_trait_rule_pass(lv, traits, tp) for lv in levels)
                    seen.setdefault(sig, (tuple(sorted(traits.items())), tp))
    return list(seen.values())


def code_behavior(hier: Hierarchy, space: str, key_code: str, map_levels: Iterable[str], code: str) -> tuple:
    """Per map level: whether a record with `code` passes the gate and reaches the key."""
    sig = []
    for lv in map_levels:
        gate_pol, proj = catalog.MAP_LEVELS[lv][1], catalog.MAP_LEVELS[lv][2]
        gate = True if gate_pol is None else (
            mapping.v1_gate(hier, code) if gate_pol == "v1_gate" else mapping.who_map(hier, code, gate_pol)[0] is not None)
        target = code if space == "cm" else mapping.who_map(hier, code, proj)[0]
        sig.append(bool(gate and target == key_code))
    return tuple(sig)


def key_codes(hier: Hierarchy, space: str, key_code: str, map_levels: Iterable[str]) -> list[str]:
    """CM codes whose projection reaches the key under some map level, one per behaviour (up to 2 fallbacks)."""
    if space == "cm":
        return [key_code] if any(code_behavior(hier, space, key_code, map_levels, key_code)) else []
    base = key_code[:3]
    cands = [key_code[:3] + ("." + key_code[3:] if len(key_code) > 3 else ""), base]
    cands += [f"{base}.{a}{b}" for a in "0123456789" for b in "0189"][:40]
    cands += [f"{base}.{a}" for a in "0123456789"]
    out: dict[tuple, list[str]] = {}
    for c in dict.fromkeys(cands):
        sig = code_behavior(hier, space, key_code, map_levels, c)
        if any(sig):
            out.setdefault(sig, []).append(c)
    codes = []
    for sig, cs in sorted(out.items()):
        codes += cs[:2]  # two distinct codes per behaviour, so repeated codes and distinct codes both occur
    return codes


@dataclass(frozen=True)
class Alphabet:
    es: tuple[float, ...]
    cs: tuple[float, ...]
    traits: tuple[tuple[tuple[tuple[str, float], ...], str], ...]
    codes: tuple[str, ...]
    es_cuts: tuple[float, ...] = ()
    cs_cuts: tuple[float, ...] = ()
    trait_levels: tuple[str, ...] = ()
    maps: tuple[str, ...] = ()

    def entity_symbols(self) -> list[tuple]:
        return [(es, tr, tp, comp) for es in self.es for tr, tp in self.traits for comp in (False, True)]

    def concept_symbols(self) -> list[tuple]:
        return [(cs, code) for cs in self.cs for code in self.codes]

    def size(self) -> dict[str, int]:
        return {"entity": len(self.entity_symbols()), "concept": len(self.concept_symbols()),
                "es": len(self.es), "cs": len(self.cs), "traits": len(self.traits), "codes": len(self.codes)}


def alphabet(hyps: Sequence[Hypothesis], hier: Hierarchy, space: str, key_code: str) -> Alphabet:
    es_cuts, cs_cuts, trait_lv, maps = set(), set(), set(), set()
    for h in hyps:
        for run in (0, 1):
            c = h.realized(run)
            es_cuts.add(float(h.x0["ent_thr"]) if run == 0 else float(h.x1["ent_thr"]))
            cs_cuts.add(float(h.x0["icd_thr"]) if run == 0 else float(h.x1["icd_thr"]))
            trait_lv.add(str(c["trait"]))
            maps.add(str(c["map"]))
    return Alphabet(tuple(_band_values(es_cuts)), tuple(_band_values(cs_cuts)),
                    tuple(trait_classes(trait_lv)), tuple(key_codes(hier, space, key_code, sorted(maps))),
                    tuple(sorted(es_cuts)), tuple(sorted(cs_cuts)), tuple(sorted(trait_lv)), tuple(sorted(maps)))


# ---------------------------------------------------------------------- bundles and batch evaluation

Bundle = tuple[tuple[tuple, tuple[tuple, ...]], ...]  # ((entity symbol, (concept symbols...)), ...)

COMPETITOR_CODE = "Z99.9"


def bundle_entities(b: Bundle, first_id: int = 1) -> list[dict]:
    ents = []
    for i, ((es, traits, tp, comp), concepts) in enumerate(b):
        cons = [{"Code": code, "Score": cs} for cs, code in concepts]
        if comp:
            cons = [{"Code": COMPETITOR_CODE, "Score": 0.999}] + cons
        ents.append({"Id": first_id + i, "Type": tp, "Score": es,
                     "Traits": [{"Name": n, "Score": s} for n, s in traits], "ICD10CMConcepts": cons})
    return ents


def bundle_size(b: Bundle) -> int:
    return sum(len(c) for _, c in b)


def extensions(b: Bundle, alpha: Alphabet) -> list[Bundle]:
    out = []
    for es in alpha.entity_symbols():
        for cs in alpha.concept_symbols():
            out.append(b + ((es, (cs,)),))
    if b:
        (last_e, last_c) = b[-1]
        for cs in alpha.concept_symbols():
            out.append(b[:-1] + ((last_e, last_c + (cs,)),))
    return out


@dataclass
class BatchEval:
    """Truth tables of many bundles under one hypothesis: one core run per realized hybrid config."""

    hier: Hierarchy
    space: str
    key_code: str
    runs: int = 0

    def tables(self, bundles: Sequence[Bundle], hyp: Hypothesis) -> list[tuple[tuple, tuple]]:
        """Per bundle: (sorted D_h, truth table as tuple of Presence values over all_subsets(D_h))."""
        responses = [(i + 1, json.dumps({"Entities": bundle_entities(b), "ModelVersion": MODEL_VERSION}))
                     for i, b in enumerate(bundles)]
        ev = Evidence.from_responses(responses)
        ks = core.WHO if self.space == "who" else core.CM
        system, version = (SYSTEM_ICD10_WHO, self.hier.version) if self.space == "who" else (
            SYSTEM_ICD10CM, f"acm:{MODEL_VERSION}")
        D = sorted(hyp.D())
        cols = []
        for S in all_subsets(D):
            cfg = hyp.realized(0, frozenset(S))
            res = core.run(cfg, ev, self.hier, ks)
            self.runs += 1
            cols.append([res.state(AssocKey(i + 1, system, version, self.key_code)).value for i in range(len(bundles))])
        return [(tuple(D), tuple(col[i] for col in cols)) for i in range(len(bundles))]


# ---------------------------------------------------------------------- expansion


@dataclass
class ExpansionResult:
    classes: dict[tuple, tuple[Bundle, Hypothesis]]  # (D_h, table, obs) -> a witness history
    saturated: bool
    levels: list[dict] = field(default_factory=list)  # per L: bundles evaluated, new classes, seconds
    cut: str = ""


def l1_observation(D: tuple, table: tuple) -> tuple:
    """L1 × R-C marginal observation: finals (hashes are equal in unpatched contrasts)."""
    return (table[0], table[-1])


def expand(
    hyps: Sequence[Hypothesis],
    alpha: Alphabet,
    ev: BatchEval,
    *,
    L: int = L_MAX,
    reps_per_class: int = 2,
    time_budget: float = 60.0,
    max_bundles: int = 50_000,
    observe=l1_observation,
    frontier_by: str = "joint",
) -> ExpansionResult:
    """Breadth-first by number of concepts. A history class is (D_h, truth table, observation); the frontier
    keeps `reps_per_class` bundles per joint signature (the tuple of classes over all hypotheses), or per class
    under the first (declared) hypothesis with `frontier_by="declared"`."""
    t0 = time.perf_counter()
    classes: dict[tuple, tuple[Bundle, Hypothesis]] = {}
    frontier: list[Bundle] = [()]
    levels: list[dict] = []
    for k in range(1, L + 1):
        tk = time.perf_counter()
        cand = list(dict.fromkeys(e for b in frontier for e in extensions(b, alpha)))
        if len(cand) > max_bundles:
            return ExpansionResult(classes, False, levels, f"bundle budget at L={k} ({len(cand)} bundles)")
        joint: list[list[tuple]] = [[] for _ in cand]
        new = 0
        for h in hyps:
            if time.perf_counter() - t0 > time_budget:
                return ExpansionResult(classes, False, levels, f"time budget at L={k}")
            for i, (b, (D, tab)) in enumerate(zip(cand, ev.tables(cand, h))):
                cls = (D, tab, observe(D, tab))
                joint[i].append(cls)
                if cls not in classes:
                    classes[cls] = (b, h)
                    new += 1
        sig_rep: dict[tuple, list[Bundle]] = {}
        for b, sig in zip(cand, joint):
            reps = sig_rep.setdefault(tuple(sig) if frontier_by == "joint" else sig[0], [])
            if len(reps) < reps_per_class:
                reps.append(b)
        frontier = [b for reps in sig_rep.values() for b in reps]
        levels.append({"L": k, "bundles": len(cand), "new_classes": new, "classes": len(classes),
                       "frontier": len(frontier), "seconds": round(time.perf_counter() - tk, 3)})
        if k > 1 and new == 0:
            return ExpansionResult(classes, True, levels)
    return ExpansionResult(classes, False, levels, f"L = {L} reached with new classes")


# ---------------------------------------------------------------------- symbolization of h* (class(h*) ∈ U)


def _band_rep(v: float, cuts: Sequence[float], reps: Sequence[float]) -> float:
    """The representative with the same comparisons (>=, >) against every cut."""
    sig = tuple((v >= c, v > c) for c in cuts)
    for r in reps:
        if tuple((r >= c, r > c) for c in cuts) == sig:
            return r
    raise ValueError(f"no band for {v}")


def relevant_codes(hier: Hierarchy, space: str, key_code: str, alpha: Alphabet, codes: Iterable[str]) -> set[str]:
    return {c for c in codes if any(code_behavior(hier, space, key_code, alpha.maps, c))}


def _concepts(e: dict) -> list[dict]:
    return e.get("ICD10CMConcepts") or []


def symbolize(doc: dict, hier: Hierarchy, space: str, key_code: str, alpha: Alphabet, L: int = L_MAX) -> Bundle | None:
    """The bundle of a's candidates in a parsed response, or None when it is not representable in U."""
    ents = doc.get("Entities") or []
    rel = relevant_codes(hier, space, key_code, alpha, {c["Code"] for e in ents for c in _concepts(e)})
    ids = [e.get("Id", i + 1) for i, e in enumerate(ents)]
    trait_sig = {}
    for tr, tp in alpha.traits:
        trait_sig[tuple(_trait_rule_pass(lv, dict(tr), tp) for lv in alpha.trait_levels)] = (tr, tp)
    by_behavior: dict[tuple, list[str]] = {}
    for c in alpha.codes:
        by_behavior.setdefault(code_behavior(hier, space, key_code, alpha.maps, c), []).append(c)
    code_map: dict[str, str] = {}
    out = []
    for i, e in enumerate(ents):
        cons = _concepts(e)
        mine = [c for c in cons if c["Code"] in rel]
        if not mine:
            continue
        if ids.count(ids[i]) > 1:
            return None  # duplicate Id groups are outside U (declared simplification)
        others = [c["Score"] for c in cons if c["Code"] not in rel]
        top_mine = max(c["Score"] for c in mine)
        if others and max(others) == top_mine:
            return None  # a tie with a non-a concept is outside U
        comp = bool(others) and max(others) > top_mine
        traits = {t["Name"]: t.get("Score") or 0.0 for t in e.get("Traits") or []}
        sig = tuple(_trait_rule_pass(lv, traits, e.get("Type") or "") for lv in alpha.trait_levels)
        if sig not in trait_sig:
            return None
        concepts = []
        for c in mine:
            code = c["Code"]
            if code not in code_map:
                beh = code_behavior(hier, space, key_code, alpha.maps, code)
                used = {v for k, v in code_map.items() if code_behavior(hier, space, key_code, alpha.maps, k) == beh}
                pool = [x for x in by_behavior.get(beh, []) if x not in used]
                if not pool:
                    return None
                code_map[code] = pool[0]
            concepts.append((_band_rep(c["Score"], alpha.cs_cuts, alpha.cs), code_map[code]))
        es = _band_rep(e.get("Score") or 0.0, alpha.es_cuts, alpha.es)
        tr, tp_rep = trait_sig[sig]
        out.append(((es, tr, tp_rep, comp), tuple(concepts)))
    b: Bundle = tuple(out)
    return b if 0 < bundle_size(b) <= L else None


# ---------------------------------------------------------------------- lifting (SPEC 8.3 W_lo)


def lift_doc(doc: dict, b: Bundle, hier: Hierarchy, space: str, key_code: str, alpha: Alphabet) -> dict:
    """Replace a's candidates in `doc` by the bundle: drop a's concepts, append the bundle with fresh Ids."""
    ents = [dict(e) for e in doc.get("Entities") or []]
    rel = relevant_codes(hier, space, key_code, alpha, {c["Code"] for e in ents for c in _concepts(e)})
    for e in ents:
        e["ICD10CMConcepts"] = [c for c in _concepts(e) if c["Code"] not in rel]
    first = max([e.get("Id", i + 1) for i, e in enumerate(ents)] or [0]) + 1
    return {**doc, "Entities": ents + bundle_entities(b, first)}
