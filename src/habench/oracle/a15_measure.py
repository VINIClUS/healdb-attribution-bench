"""A15: cost of the identification reference on dev groups (run as a module; reads dev data only).

    uv run python -m habench.oracle.a15_measure --groups 20 --L 3 --max-dev 2 --budget 60

Builds the component contrast V1 → V2 (WHO space) on seeded dev groups, the truth of every changed query,
and the identification in the cells that need U. Prints per-expansion and per-query statistics as JSON.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import statistics
import time
from pathlib import Path

from habench.oracle.contrast import make_contrast
from habench.oracle.hybrids import Hybrids
from habench.oracle.reference import UniverseCache, ident_fn
from habench.oracle.truth import CellSpec, build_truth
from habench.pipeline.catalog import V1, V2
from habench.pipeline.evidence import load_evidence
from habench.pipeline.mapping import load_hierarchy

MANIFEST = Path(__file__).resolve().parents[3] / "repro" / "split_manifest.csv"
CELLS = ("L1|R-C", "L2-R|R-C", "L2-M|R-C", "L2-R-A3|R-A", "L2-R-A2|R-C")


def dev_groups() -> list[tuple[str, tuple[int, ...]]]:
    with open(MANIFEST, newline="", encoding="utf-8") as fh:
        rows = [r for r in csv.DictReader(fh) if r["partition"] == "dev"]  # never the sealed test partition
    return [(r["group_id"], tuple(sorted(int(m) for m in r["medications"].split(";")))) for r in rows]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--groups", type=int, default=20)
    ap.add_argument("--queries", type=int, default=5, help="changed queries per contrast")
    ap.add_argument("--L", type=int, default=3)
    ap.add_argument("--max-dev", type=int, default=2)
    ap.add_argument("--budget", type=float, default=60.0)
    ap.add_argument("--seed", type=int, default=20260930)
    a = ap.parse_args(argv)
    rng = random.Random(a.seed)
    groups = rng.sample(dev_groups(), a.groups)
    hier = load_hierarchy("v1")
    ev_all = load_evidence("v1", [m for _, ms in groups for m in ms])
    cache = UniverseCache(L=a.L, max_dev=a.max_dev, time_budget=a.budget)
    cells = [CellSpec.of(*c.split("|")) for c in CELLS]
    per_query = []
    t0 = time.perf_counter()
    for gid, meds in groups:
        ev = ev_all.subset(meds)
        c = make_contrast(gid, gid, meds, "who", V1, V2)
        h = Hybrids(c, ev, hier)
        keys = sorted(h.run(frozenset()).present | h.run(frozenset(c.D)).present)
        changed = [k for k in keys if h.state(frozenset(), k) != h.state(frozenset(c.D), k)]
        pick = rng.sample(changed, min(a.queries, len(changed)))
        tq = time.perf_counter()
        t = build_truth(h, [(f"q{i}", k) for i, k in enumerate(pick)], partition="dev", scenario_family="X",
                        cells=cells, ident=ident_fn(c, ev, hier, cache))
        dt = time.perf_counter() - tq
        print(json.dumps({"group": gid, "meds": len(meds), "keys": len(keys), "changed": len(changed),
                          "queries": len(pick), "seconds": round(dt, 1), "expansions": len(cache.stats)}), flush=True)
        for q in t.queries:
            row = {"group": gid, "code": q.key.code, "complete": q.complete, "seconds_contrast": round(dt, 2)}
            for (v, cap), i in q.ident.items():
                row[f"{v}|{cap}"] = {"state": i.state, "W_lo": len(i.W_lo), "W_hi": len(i.W_hi),
                                     "saturated": i.saturated}
            per_query.append(row)
    summary = {"cells": {}}
    for cell in CELLS:
        rows = [r[cell] for r in per_query if cell in r]
        states = [r["state"] for r in rows]
        summary["cells"][cell] = {
            "n": len(rows), "states": {s: states.count(s) for s in sorted(set(states))},
            "saturated": sum(r["saturated"] for r in rows), "mean_W_hi": statistics.mean([r["W_hi"] for r in rows]) if rows else None,
        }
    print(json.dumps({"args": vars(a), "seconds": round(time.perf_counter() - t0, 1), "queries": len(per_query),
                      "expansions": cache.stats, "summary": summary}, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
