"""B3 — native reference with replay (protocol §10; design §D).

Replay-validate (∅ and D against the observed finals), then evaluate every singleton and every leave-one-out
complement of D, jointly for all queries, at most 2|D| + 2 evaluations under the same budget as M. Per changed query:
- sufficient singletons → `explicacao_verificada` with their family;
- none, and every leave-one-out complement insufficient → `explicacao_verificada` {{D}};
- a needed hybrid unavailable → `contrafactual_indisponivel`; budget spent first → `orcamento_esgotado`;
- otherwise (a complement is sufficient, no singleton is) the minimal sets lie strictly between and B3 does not look
  there → `informacao_insuficiente` ("ambiguidade").
No dummy pruning and no identification reasoning.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from habench.methods.base import (
    AMBIGUIDADE,
    ORCAMENTO,
    OUTPUT_DIFF_ONLY,
    REPLAY_INVALIDO,
    SEM_RESPOSTA_ARMAZENADA,
    BudgetExhausted,
    Certificate,
    Env,
    EvalResult,
    Explanation,
    Query,
    Unavailable,
    abstain,
    canonical_set,
    changed,
    final_certificates,
    same_presence,
    validated,
)
from habench.types import OutputState


class B3:
    name = "b3"

    def explain(self, env: Env, queries: Sequence[Query]) -> Mapping[str, Explanation]:
        open_q = [q for q in queries if changed(env, q.key)]
        out = {q.qid: abstain(q.qid, OutputState.AUSENCIA_DE_MUDANCA, "") for q in queries if q not in open_q}
        if not open_q:
            return out
        D = frozenset(env.factors())

        def all_open(state: OutputState, reason: str) -> dict[str, Explanation]:
            return out | {q.qid: abstain(q.qid, state, reason) for q in open_q}

        if env.capability() == "R-C":
            return all_open(OutputState.INFORMACAO_INSUFICIENTE, OUTPUT_DIFF_ONLY)
        try:
            r0, r1 = env.evaluate(frozenset()), env.evaluate(D)
        except BudgetExhausted:
            return all_open(OutputState.ORCAMENTO_ESGOTADO, ORCAMENTO)
        except Unavailable:
            return all_open(OutputState.INFORMACAO_INSUFICIENTE, SEM_RESPOSTA_ARMAZENADA)
        if not (same_presence(r0.presence, env.final("x0")) and same_presence(r1.presence, env.final("x1"))):
            return all_open(OutputState.INFORMACAO_INSUFICIENTE, REPLAY_INVALIDO)

        order = sorted(frozenset({f}) for f in D) + sorted((D - {f} for f in D), key=lambda s: sorted(D - s))
        seen: dict[frozenset[str], EvalResult] = {frozenset(): r0, D: r1}
        unknown: set[frozenset[str]] = set()
        exhausted = False
        for s in order:
            if s in seen or s in unknown:
                continue
            try:
                seen[s] = env.evaluate(s)
            except Unavailable:
                unknown.add(s)
            except BudgetExhausted:
                exhausted = True
                break

        singles = [frozenset({f}) for f in sorted(D)]
        complements = [D - {f} for f in sorted(D)]
        for q in open_q:
            target = r1.state(q.key)

            def suff(s: frozenset[str]) -> bool:
                return seen[s].state(q.key) == target

            certs = final_certificates(D) + tuple(
                Certificate("eval", canonical_set(s), suff(s)) for s in seen if s and s != D
            )
            found = [s for s in singles if s in seen and suff(s)]
            singles_done = all(s in seen for s in singles)
            if found and singles_done:
                family = tuple(canonical_set(s) for s in found)
                out[q.qid] = Explanation(q.qid, OutputState.EXPLICACAO_VERIFICADA, (family,), certs)
            elif singles_done and all(s in seen and not suff(s) for s in complements):
                out[q.qid] = Explanation(q.qid, OutputState.EXPLICACAO_VERIFICADA, ((canonical_set(D),),), certs)
            elif any(s in unknown for s in singles + complements):
                out[q.qid] = abstain(q.qid, OutputState.CONTRAFACTUAL_INDISPONIVEL, SEM_RESPOSTA_ARMAZENADA)
            elif exhausted:
                out[q.qid] = abstain(q.qid, OutputState.ORCAMENTO_ESGOTADO, ORCAMENTO)
            else:
                out[q.qid] = abstain(q.qid, OutputState.INFORMACAO_INSUFICIENTE, AMBIGUIDADE)
        return {k: validated(v) for k, v in out.items()}
