"""`uv run python -m habench.runner --partition dev --seed 20260930 --max-groups 5 --name smoke`

Runs the efficient matrix over dev or cal as a resumable batch (see `habench.runner.batch`). The test partition is
refused (`SealedError`) before anything is loaded.
"""

from __future__ import annotations

import argparse
import json
import resource
import sys
import time

from habench.runner.batch import Batch, load_inputs
from habench.runner.check import check_m
from habench.runner.matrix import DEFAULT_METHODS, METHODS


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="habench.runner")
    ap.add_argument("--partition", required=True, choices=("dev", "cal", "test"))
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--name", required=True, help="batch name under runs/<partition>/")
    ap.add_argument("--max-groups", type=int, default=None)
    ap.add_argument("--methods", default=",".join(DEFAULT_METHODS))
    ap.add_argument("--info-fraction", type=float, default=0.2)
    ap.add_argument("--shard", default="0/1", help="i/n: run only contrasts i, i+n, ... (one process per CPU)")
    a = ap.parse_args(argv)
    t0 = time.monotonic()
    methods = tuple(m for m in a.methods.split(",") if m)
    unknown = set(methods) - set(METHODS)
    if unknown:
        ap.error(f"unknown methods {sorted(unknown)}")

    from habench.scenarios.generate import generate

    evidence, hier, texts = load_inputs(a.partition)
    scenarios = generate(a.partition, seed=a.seed, evidence=evidence, hier=hier, max_groups=a.max_groups)
    scenarios = scenarios[0] if isinstance(scenarios, tuple) else scenarios
    i, n = (int(x) for x in a.shard.split("/"))
    scenarios = scenarios[i::n]  # contrasts write disjoint files; create the HMAC key before launching shards
    batch = Batch(a.partition, a.name, evidence, hier, texts, methods=methods, info_fraction=a.info_fraction,
                  seed=a.seed)
    counts = batch.run(scenarios, progress=lambda s: print(s, file=sys.stderr, flush=True))
    check = check_m(batch.data_dir, a.partition, a.name) if "m" in methods else None
    self_ru, child_ru = resource.getrusage(resource.RUSAGE_SELF), resource.getrusage(resource.RUSAGE_CHILDREN)
    counts |= {
        "wall_seconds": round(time.monotonic() - t0, 1),
        "cpu_seconds": round(self_ru.ru_utime + self_ru.ru_stime + child_ru.ru_utime + child_ru.ru_stime, 1),
        "peak_rss_mib_parent": round(self_ru.ru_maxrss / 1024, 1),
        "peak_rss_mib_children": round(child_ru.ru_maxrss / 1024, 1),
        "scenarios": len(scenarios),
    }
    if check is not None:
        counts |= {"m_checked_queries": check.queries, "m_mismatches": len(check.mismatches)}
        for m in check.mismatches[:20]:
            print("mismatch", *m, file=sys.stderr)
    print(json.dumps(counts, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
