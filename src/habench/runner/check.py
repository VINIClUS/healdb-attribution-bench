"""Acceptance check of a finished batch: M against the oracle under L2-M × R-A at b = 64 (T13, T21).

For every eligible query of every contrast: unchanged → `ausencia_de_mudanca`; changed with a complete family →
`explicacao_verificada` with exactly F*; changed with an incomplete family → `contrafactual_indisponivel`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from habench.oracle.truth import read_truth
from habench.views.layout import BrokerSide, check_partition


@dataclass
class CheckResult:
    contrasts: int = 0
    queries: int = 0
    mismatches: list[tuple[str, str, str]] = field(default_factory=list)  # (cid, qid, detail)


def check_m(data_dir: Path, partition: str, batch: str, method: str = "m") -> CheckResult:
    check_partition(partition)
    truth_dir = data_dir / "truth" / partition
    res = CheckResult()
    for tpath in sorted((truth_dir / "contrasts").glob("*.json")):
        truth = read_truth(tpath)
        run = data_dir / "runs" / partition / batch / truth.cid / f"L2-M__R-A__b64__{method}.json"
        if not run.exists():
            continue
        rec = json.loads(run.read_text())
        side = BrokerSide.from_json((truth_dir / "views" / f"{rec['vid']}.json").read_text())
        member = dict(side.handles)
        res.contrasts += 1
        for qt in truth.queries:
            if not qt.eligible:
                continue
            e = rec["explanations"][qt.qid]
            if not qt.changed:
                ok = e["state"] == "ausencia_de_mudanca"
            elif qt.complete:
                fams = e["families"]
                fam = frozenset(frozenset(member.get(h, h) for h in s) for s in fams[0]) if fams else None
                ok = e["state"] == "explicacao_verificada" and fam == qt.family
            else:
                ok = e["state"] == "contrafactual_indisponivel"
            res.queries += 1
            if not ok:
                res.mismatches.append((truth.cid, qt.qid, f"{e['state']} {e['families']} vs {qt.family}"))
    return res
