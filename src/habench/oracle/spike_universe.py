"""A15 spike: cost of the U expansion for one contrast shape under L1 × R-C (run as a module).

    uv run python -m habench.oracle.spike_universe [--key E11] [--L 3] [--max-dev 3] [--budget 120]

Prints the hypothesis count, the alphabet, and per level the bundles, classes and seconds. No data is read:
under L1 the expansion does not depend on the group's evidence (only lifting does).
"""

from __future__ import annotations

import argparse
import json
import time

from habench.oracle import toy
from habench.oracle.universe import Alphabet, BatchEval, alphabet, expand, hypotheses
from habench.pipeline.catalog import V1, V2


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--key", default="E11")
    ap.add_argument("--space", default="who")
    ap.add_argument("--L", type=int, default=3)
    ap.add_argument("--max-dev", type=int, default=3)
    ap.add_argument("--budget", type=float, default=120.0)
    ap.add_argument("--reps", type=int, default=1)
    ap.add_argument("--frontier", default="declared")
    a = ap.parse_args(argv)
    hier = toy.hierarchy()
    t = time.perf_counter()
    hyps = hypotheses(V1, V2, code_link=False, max_dev=a.max_dev)
    alpha: Alphabet = alphabet(hyps, hier, a.space, a.key)
    ev = BatchEval(hier, a.space, a.key)
    res = expand(hyps, alpha, ev, L=a.L, time_budget=a.budget, reps_per_class=a.reps, frontier_by=a.frontier)
    fams = {}
    for (D, tab, obs), _ in res.classes.items():
        from habench.oracle.hybrids import all_subsets
        from habench.oracle.families import analyze

        table = dict(zip(all_subsets(D), tab))
        r = analyze(D, table) if table else None
        if r and r.changed:
            fams.setdefault(obs, set()).add(r.family)
    print(json.dumps({
        "hypotheses": len(hyps), "alphabet": alpha.size(), "levels": res.levels, "saturated": res.saturated,
        "cut": res.cut, "core_runs": ev.runs, "seconds": round(time.perf_counter() - t, 2),
        "families_per_observation": {str(k): len(v) for k, v in fams.items()},
    }, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
