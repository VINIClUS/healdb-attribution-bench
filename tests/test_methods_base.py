import json
import subprocess
import sys
from pathlib import Path

import pytest

from habench.methods.base import INVALID_OUTPUT, Explanation, canonical_family, validated
from habench.types import OutputState

EXAMPLES = {e["id"]: e for e in json.loads((Path(__file__).parent / "data" / "spec_examples.json").read_text())["examples"]}


def _fams(raw) -> tuple:
    return tuple(tuple(tuple(s) for s in fam) for fam in raw)


@pytest.mark.parametrize("case", EXAMPLES["EX-23"]["cases"], ids=lambda c: f"{c['state']}-{c['families']}")
def test_ex23_output_validation(case):
    e = Explanation(qid="q", state=OutputState(case["state"]), families=_fams(case["families"]), reason="r")
    out = validated(e)
    if case["expected_valid"]:
        assert out == e
    else:
        assert out.state == OutputState.FALHA_DE_EXECUCAO and out.reason == INVALID_OUTPUT and out.families == ()


def test_canonical_family_order():
    assert canonical_family([{"b", "c"}, {"a"}, {"c", "b"}]) == (("a",), ("b", "c"))


def test_base_imports_nothing_forbidden():
    code = (
        "import sys, habench.methods.base, habench.env.table\n"
        "bad = [m for m in sys.modules if m.startswith(('habench.pipeline', 'habench.oracle', 'habench.scenarios'))]\n"
        "assert not bad, bad\n"
    )
    subprocess.run([sys.executable, "-c", code], check=True)
