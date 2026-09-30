"""Resumable batch over dev or cal (T21): scenarios → truth → views → isolated method runs.

Layout under the data dir (never inside the repo):
- `truth/<partition>/contrasts/<cid>.json`: the truth package (β's `write_truth`);
- `truth/<partition>/scenarios/<cid>.json`: family, subfamily, inclusion probabilities, notes (truth side only);
- `truth/<partition>/views/<vid>.json`: the broker side of each view (`views.layout`);
- `views/<partition>/<vid>/`: the views mounted for methods;
- `runs/<partition>/<batch>/<cid>/<view>__<capability>__b<budget>__<method>.json`: one output per cell.

Every step skips work whose output already exists, so an interrupted batch resumes where it stopped. The test
partition is refused before anything is loaded (`SealedError`).
"""

from __future__ import annotations

import json
import random
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from habench.env.broker import BrokerEnv
from habench.env.rpc import RunOutcome, run_isolated
from habench.methods.base import Explanation, Query
from habench.oracle.contrast import Contrast
from habench.oracle.hybrids import Hybrids
from habench.oracle.truth import CellSpec, build_truth, write_truth
from habench.pipeline.evidence import Evidence
from habench.pipeline.mapping import Hierarchy
from habench.runner.matrix import DEFAULT_METHODS, METHODS, Cell, cells
from habench.types import SealedError
from habench.views.build import Texts, build_view
from habench.views.layout import DATA_DIR, check_partition, hid, load_key, views_root

BUGDOC_DIR = Path(__file__).resolve().parents[3] / "third_party" / "bugdoc"


@dataclass
class Batch:
    partition: str
    name: str
    evidence: Evidence
    hier: Hierarchy
    texts: Mapping[int, Texts]
    data_dir: Path = DATA_DIR
    methods: Sequence[str] = DEFAULT_METHODS  # add "m_lenient" on cal for the rigor sweep
    info_fraction: float = 0.2  # seeded share of F/M/O/X contrasts crossed with every view (family I)
    seed: int = 0
    timeout: float = 600.0
    log: list[dict] = field(default_factory=list)

    def __post_init__(self) -> None:
        check_partition(self.partition)
        self.key = load_key(self.data_dir, create=True)
        self.truth_dir = self.data_dir / "truth" / self.partition
        self.runs_dir = self.data_dir / "runs" / self.partition / self.name

    # ------------------------------------------------------------------ steps

    def cells_for(self, scenario) -> list[Cell]:
        c: Contrast = scenario.contrast
        cross = None
        if scenario.family in ("F", "M", "O", "X"):
            cross = random.Random(hid(self.key, "cross", c.cid)).random() < self.info_fraction
        return cells(scenario.family, has_prep=bool(c.prep_factors), methods=self.methods, info_cross=cross)

    def truth(self, scenario, run_cells: Iterable[Cell]) -> Path:
        c: Contrast = scenario.contrast
        path = self.truth_dir / "contrasts" / f"{c.cid}.json"
        if path.exists():
            return path
        hyb = Hybrids(c, self.evidence, self.hier)
        declared = Hybrids(c, self.evidence, self.hier, levels="declared")
        specs = sorted({(x.view, x.capability) for x in run_cells if x.runs})
        # dummy and expressibility use β's defaults, which the broker shares (one core path for truth and replay)
        t = build_truth(
            hyb, scenario.queries, partition=self.partition, scenario_family=scenario.family,
            cells=[CellSpec.of(v, cap) for v, cap in specs], declared_hybrids=declared,
        )
        write_truth(t, path)
        meta = {"cid": c.cid, "family": scenario.family, "subfamily": scenario.subfamily,
                "inclusion": scenario.inclusion, "notes": list(scenario.notes)}
        (self.truth_dir / "scenarios").mkdir(parents=True, exist_ok=True)
        (self.truth_dir / "scenarios" / f"{c.cid}.json").write_text(json.dumps(meta, sort_keys=True) + "\n")
        return path

    def view(self, contrast: Contrast, view: str):
        return build_view(contrast, view, evidence=self.evidence, hier=self.hier, texts=self.texts,
                          partition=self.partition, key=self.key, data_dir=self.data_dir)

    def run_cell(self, scenario, cell: Cell, view_dir: Path, side) -> Path:
        c: Contrast = scenario.contrast
        out = self.runs_dir / c.cid / f"{cell.view}__{cell.capability}__b{cell.budget}__{cell.method}.json"
        if out.exists():
            return out
        record = {"cid": c.cid, "vid": side.vid, "view": cell.view, "capability": cell.capability,
                  "budget": cell.budget, "method": cell.method}
        if not cell.runs:
            record["equivalent_to"] = list(cell.equivalent_to)
        else:
            env = BrokerEnv(side, c, self.evidence, self.hier, view_dir, cell.capability, cell.budget)
            queries = [Query(qid, key) for qid, key in scenario.queries]
            random.Random(hid(self.key, "qorder", c.cid, side.vid)).shuffle(queries)  # SPEC 11.1
            t0 = time.monotonic()
            outcome: RunOutcome = run_isolated(
                METHODS[cell.method], env, queries, view_dir=view_dir, truth_root=self.data_dir / "truth",
                extra_read=[BUGDOC_DIR], timeout=self.timeout,
            )
            record |= {
                "explanations": {q: explanation_json(e) for q, e in sorted(outcome.explanations.items())},
                "meter": {"evaluations": outcome.meter.evaluations, "bytes_read": outcome.meter.bytes_read,
                          "cpu_seconds": outcome.meter.cpu_seconds, "peak_rss": outcome.meter.peak_rss,
                          "child_cpu_seconds": outcome.child_cpu_seconds, "wall_seconds": time.monotonic() - t0},
                "error": outcome.error,
                "log": [sorted(s) for s in env.ledger.log],
            }
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_name(out.name + ".tmp")
        tmp.write_text(json.dumps(record, sort_keys=True) + "\n")
        tmp.replace(out)
        return out

    def run(self, scenarios: Sequence, progress: Callable[[str], None] | None = None) -> dict:
        counts = {"contrasts": 0, "cells_run": 0, "cells_equivalent": 0, "errors": 0}
        for sc in scenarios:
            if sc.contrast.meds and self.partition == "test":  # defensive: generate() already refuses
                raise SealedError("the test partition is sealed")
            run_cells = self.cells_for(sc)
            self.truth(sc, run_cells)
            sides = {}
            for view in sorted({x.view for x in run_cells if x.runs}):
                sides[view] = self.view(sc.contrast, view)
            for cell in run_cells:
                src = cell.equivalent_to[0] if cell.equivalent_to else cell.view
                if src not in sides:
                    sides[src] = self.view(sc.contrast, src)
                view_dir, side = sides[src]
                path = self.run_cell(sc, cell, view_dir, side)
                counts["cells_run" if cell.runs else "cells_equivalent"] += 1
                if cell.runs and json.loads(path.read_text()).get("error"):
                    counts["errors"] += 1
            counts["contrasts"] += 1
            if progress:
                progress(f"{counts['contrasts']}/{len(scenarios)} {sc.contrast.cid}")
        return counts


def explanation_json(e: Explanation) -> dict:
    return {
        "state": e.state.value,
        "families": [[list(s) for s in fam] for fam in e.families],
        "certificates": [[c.kind, list(c.subject), c.value] for c in e.certificates],
        "reason": e.reason,
        "confidence": e.confidence,
        "notes": list(e.notes),
    }


def load_inputs(partition: str, snap: str = "v1") -> tuple[Evidence, Hierarchy, dict[int, Texts]]:
    """Real dev/cal inputs: responses, the fixed hierarchy and the per-medication texts (V1 submitted text)."""
    check_partition(partition)
    from habench.data import groups, splits
    from habench.historical.text_v1 import v1_text
    from habench.pipeline.mapping import load_hierarchy

    evidence = splits.evidence_for(partition, snap)
    texts_raw = groups.load_texts(snap)
    texts = {}
    for m in evidence.meds:
        pt, en = texts_raw.get(m, ("", ""))  # a medication without a stored text shows empty texts, never a guess
        texts[m] = Texts(pt or "", en or "", v1_text(en) if en else "")
    return evidence, load_hierarchy(snap), texts


def views_dir(partition: str, data_dir: Path = DATA_DIR) -> Path:
    return views_root(partition, data_dir)
