"""Method-side reference BFS for minimal sufficient sets (SPEC §6.3).

Runs inside the isolated method process: no import of `habench.pipeline`, `habench.oracle` or `habench.scenarios`.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from itertools import combinations

from habench.methods.base import BudgetExhausted, EvalResult, FamilyT, Unavailable, canonical_family
from habench.types import AssocKey


@dataclass(frozen=True)
class SearchResult:
    families: Mapping[str, FamilyT]  # open queries only: minimal sufficient sets found
    complete: Mapping[str, bool]  # open queries only, §6.3 step 4
    unchanged: frozenset[str]  # state(∅) == state(D): not searched
    evaluated: tuple[frozenset[str], ...]  # distinct sets evaluated, in call order (∅ and D first)
    unknown: Mapping[frozenset[str], str]  # sets skipped because evaluate raised Unavailable -> reason
    results: Mapping[frozenset[str], EvalResult]
    exhausted: bool  # BudgetExhausted was hit


def bfs(
    evaluate: Callable[[frozenset[str]], EvalResult],
    D: Sequence[str],
    queries: Mapping[str, AssocKey],
    dummies: Mapping[str, frozenset[str]] | None = None,
) -> SearchResult:
    names = tuple(sorted(D))
    full = frozenset(names)
    dummies = dummies or {}
    evaluated: list[frozenset[str]] = []
    results: dict[frozenset[str], EvalResult] = {}

    def call(s: frozenset[str]) -> EvalResult:
        r = evaluate(s)
        if s not in results:
            evaluated.append(s)
            results[s] = r
        return r

    # Replay validation: failures propagate to the caller.
    r0 = call(frozenset())
    r_full = call(full)

    target = {q: r_full.state(key) for q, key in queries.items()}
    unchanged = frozenset(q for q, key in queries.items() if r0.state(key) == target[q])
    open_qs = [q for q in queries if q not in unchanged]
    found: dict[str, list[frozenset[str]]] = {q: [] for q in open_qs}
    skipped: dict[str, list[frozenset[str]]] = {q: [] for q in open_qs}  # unknown sets that counted for q
    unknown: dict[frozenset[str], str] = {}
    exhausted = False

    def pruned(q: str, s: frozenset[str]) -> bool:
        return any(t <= s for t in found[q]) or bool(s & dummies.get(q, frozenset()))

    for k in range(1, len(names)):
        if exhausted or not open_qs:
            break
        for combo in combinations(names, k):
            s = frozenset(combo)
            live = [q for q in open_qs if not pruned(q, s)]
            if not live:
                continue
            try:
                r = call(s)
            except Unavailable as exc:
                unknown[s] = exc.reason
                for q in live:
                    skipped[q].append(s)
                continue
            except BudgetExhausted:
                exhausted = True
                break
            for q in live:
                if r.state(queries[q]) == target[q]:
                    found[q].append(s)

    if not exhausted:
        for q in open_qs:
            if not any(t <= full for t in found[q]):  # D is sufficient by definition (§6.3 step 3)
                found[q].append(full)

    families = {q: canonical_family(found[q]) for q in open_qs}
    complete = {
        q: not exhausted and all(any(t < s for t in found[q]) for s in skipped[q]) for q in open_qs
    }
    return SearchResult(families, complete, unchanged, tuple(evaluated), unknown, results, exhausted)
