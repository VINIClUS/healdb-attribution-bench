"""`uv run python -m habench.runner --partition dev --seed 20260930 --max-groups 5 --name smoke`

Runs the efficient matrix over dev or cal as a resumable batch (see `habench.runner.batch`). The test partition is
refused (`SealedError`) before anything is loaded.
"""

from __future__ import annotations

import argparse
import json
import sys

from habench.runner.batch import Batch, load_inputs
from habench.runner.matrix import DEFAULT_METHODS, METHODS


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="habench.runner")
    ap.add_argument("--partition", required=True, choices=("dev", "cal", "test"))
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--name", required=True, help="batch name under runs/<partition>/")
    ap.add_argument("--max-groups", type=int, default=None)
    ap.add_argument("--methods", default=",".join(DEFAULT_METHODS))
    ap.add_argument("--info-fraction", type=float, default=0.2)
    a = ap.parse_args(argv)
    methods = tuple(m for m in a.methods.split(",") if m)
    unknown = set(methods) - set(METHODS)
    if unknown:
        ap.error(f"unknown methods {sorted(unknown)}")

    from habench.scenarios.generate import generate

    evidence, hier, texts = load_inputs(a.partition)
    scenarios = generate(a.partition, seed=a.seed, evidence=evidence, hier=hier, max_groups=a.max_groups)
    scenarios = scenarios[0] if isinstance(scenarios, tuple) else scenarios
    batch = Batch(a.partition, a.name, evidence, hier, texts, methods=methods, info_fraction=a.info_fraction,
                  seed=a.seed)
    counts = batch.run(scenarios, progress=lambda s: print(s, file=sys.stderr, flush=True))
    print(json.dumps(counts, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
