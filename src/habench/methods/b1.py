"""B1 — divergent declared configuration (protocol §10): lists the declared factors that changed.

One declared factor → `explicacao_verificada` {{f}}; several → `alternativas` of singletons; none →
`informacao_insuficiente`. B1 issues no certificates, so a right answer is never sustained (§9.2).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from habench.methods.base import OUTPUT_DIFF_ONLY, Env, Explanation, Query, abstain, changed, validated
from habench.types import OutputState


def declared_diff(env: Env) -> tuple[str, ...]:
    c0, c1 = env.config("x0"), env.config("x1")
    return tuple(sorted(k for k in c0.keys() | c1.keys() if c0.get(k) != c1.get(k)))


class B1:
    name = "b1"

    def explain(self, env: Env, queries: Sequence[Query]) -> Mapping[str, Explanation]:
        diff = declared_diff(env)
        out: dict[str, Explanation] = {}
        for q in queries:
            if not changed(env, q.key):
                out[q.qid] = abstain(q.qid, OutputState.AUSENCIA_DE_MUDANCA, "")
            elif not diff:
                out[q.qid] = abstain(q.qid, OutputState.INFORMACAO_INSUFICIENTE, OUTPUT_DIFF_ONLY)
            elif len(diff) == 1:
                out[q.qid] = Explanation(q.qid, OutputState.EXPLICACAO_VERIFICADA, (((diff[0],),),))
            else:
                out[q.qid] = Explanation(q.qid, OutputState.ALTERNATIVAS, tuple(((f,),) for f in diff))
        return {k: validated(v) for k, v in out.items()}
