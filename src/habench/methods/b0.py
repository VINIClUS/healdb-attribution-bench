"""B0 — output difference (protocol §10): descriptive, no causal capability."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from habench.methods.base import OUTPUT_DIFF_ONLY, Env, Explanation, Query, abstain, changed
from habench.types import OutputState


class B0:
    name = "b0"

    def explain(self, env: Env, queries: Sequence[Query]) -> Mapping[str, Explanation]:
        return {
            q.qid: abstain(q.qid, OutputState.INFORMACAO_INSUFICIENTE, OUTPUT_DIFF_ONLY)
            if changed(env, q.key)
            else abstain(q.qid, OutputState.AUSENCIA_DE_MUDANCA, "")
            for q in queries
        }
