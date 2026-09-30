"""B2 — first divergence (protocol §10; design §D): locate the first artifact/stage that differs and report its
factors as candidates, without concluding causality.

Stages in pipeline order: the association's response (x0 vs x1 raw response of its medication → the opaque patch
handles), then its records in the stored trace (L2-M): a record present in one run only → `occ`/`sel`; otherwise the
first core stage whose verdict differs (`map`, trait stages → `trait`, `icd_thr`, `ent_thr`). Candidates are
intersected with the evaluable handles. One candidate → `explicacao_verificada` {{f}}, several → `alternativas` of
singletons, both without certificates and noted `noncausal`. Without a stored trace (L1, L2-R) B2 degenerates to B1.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

from habench.methods.b1 import B1
from habench.methods.base import Env, Explanation, Query, abstain, changed, validated
from habench.types import AssocKey, OutputState

STAGE_ORDER = ("map", "trait_veto", "trait_hyp", "icd_thr", "ent_thr", "trait_required", "trait_type")
STAGE_FACTOR = {"map": "map", "icd_thr": "icd_thr", "ent_thr": "ent_thr"}


def _read(env: Env, kind: str, run: str):
    refs = [r for r in env.artifacts() if r.kind == kind and r.run == run]
    return json.loads(env.read(refs[0])) if refs else None


def _records(trace: dict, key: AssocKey) -> dict[tuple, dict[str, bool]]:
    """(med, code) of the records with `key` → stage verdicts."""
    target = [key.med, key.system, key.version, key.code]
    rids = {r["rid"]: (r["med"], r["code"]) for r in trace["records"] if r["key"] == target}
    out: dict[tuple, dict[str, bool]] = {v: {} for v in rids.values()}
    for d in trace["decisions"]:
        if d["ref"] in rids:
            out[rids[d["ref"]]][d["stage"]] = d["verdict"]
    return out


def first_divergence(env: Env, key: AssocKey, handles: Sequence[str]) -> tuple[str, ...] | None:
    """Candidate factors of the first divergent stage, or None when no stored trace reaches the association."""
    kinds = {r.kind for r in env.artifacts()}
    if "trace" not in kinds:
        return None
    for kind in ("acm_response", "acm_response_top1"):
        if kind in kinds:
            r0, r1 = _read(env, kind, "x0"), _read(env, kind, "x1")
            if r0 and r1 and r0.get(str(key.med)) != r1.get(str(key.med)):
                return tuple(h for h in handles if h.startswith("ev:"))
            break
    t0, t1 = _read(env, "trace", "x0"), _read(env, "trace", "x1")
    if not t0 or not t1 or "records" not in t0:
        return None
    a, b = _records(t0, key), _records(t1, key)
    if a.keys() != b.keys():
        return tuple(h for h in ("occ", "sel") if h in handles)
    for stage in STAGE_ORDER:
        if any(a[r].get(stage) != b[r].get(stage) for r in a):
            f = STAGE_FACTOR.get(stage, "trait")
            return (f,) if f in handles else ()
    return ()


class B2:
    name = "b2"

    def explain(self, env: Env, queries: Sequence[Query]) -> Mapping[str, Explanation]:
        handles = tuple(env.factors())
        fallback = B1().explain(env, queries)
        out: dict[str, Explanation] = {}
        for q in queries:
            if not changed(env, q.key):
                out[q.qid] = abstain(q.qid, OutputState.AUSENCIA_DE_MUDANCA, "")
                continue
            cands = first_divergence(env, q.key, handles)
            if not cands:
                out[q.qid] = fallback[q.qid]
            elif len(cands) == 1:
                out[q.qid] = Explanation(q.qid, OutputState.EXPLICACAO_VERIFICADA, (((cands[0],),),), notes=("noncausal",))
            else:
                out[q.qid] = Explanation(q.qid, OutputState.ALTERNATIVAS, tuple(((f,),) for f in sorted(cands)),
                                         notes=("noncausal",))
        return {k: validated(v) for k, v in out.items()}
