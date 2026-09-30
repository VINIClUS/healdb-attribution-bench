import json
from pathlib import Path

import pytest

from habench.oracle import truth
from habench.views import profiles
from habench.views.profiles import kinds, split_view

EX22 = next(e for e in json.loads((Path(__file__).parent / "data" / "spec_examples.json").read_text())["examples"]
            if e["id"] == "EX-22")


def test_table_71():
    assert kinds("L1") == {"source_pt", "final", "hashes", "config_declared"}
    assert kinds("N1") == {"source_pt", "final", "config_declared", "translation_en", "acm_response", "trace"}
    assert kinds("N2") == kinds("N1") | {"submitted_text"}
    assert "hashes" not in kinds("N1") and "code_link" not in kinds("N2")
    assert kinds("L3-R") == kinds("L2-R") and kinds("L3-M") == kinds("L2-M")


def test_ex22_profiles_and_chain():
    for name, items in EX22["profiles"].items():
        assert kinds(name) == set(items)
    chain = [kinds(v) for v in EX22["chain"]]
    assert all(a < b for a, b in zip(chain, chain[1:]))


def test_ex22_ablations_remove_exactly_one_item():
    for a, spec in EX22["ablations"].items():
        for base in spec["bases"]:
            got = kinds(f"{base}-{a}")
            want = (kinds(base) - {spec["remove"]}) | ({spec["add"]} if spec["add"] else set())
            assert got == want
            assert spec["remove"] in kinds(base) and spec["remove"] not in got
        for base in set(EX22["chain"][1:]) - set(spec["bases"]):
            with pytest.raises(ValueError):
                kinds(f"{base}-{a}")


def test_ex22_combined_are_unions_of_known_ablations():
    for c, parts in EX22["combined"].items():
        assert set(parts) <= set(EX22["ablations"])
        for base in ("L2-R", "L2-M"):
            if c == "C2" and base == "L2-R":
                with pytest.raises(ValueError):
                    kinds(f"{base}-{c}")
                continue
            removed = kinds(base) - kinds(f"{base}-{c}")
            assert removed == {EX22["ablations"][a]["remove"] for a in parts}


def test_absent_item_is_an_error():
    for bad in ("L1-A1", "L1-A2", "N1-A1", "N2-A3", "L2-R-A6", "N1-A6", "L2-R-C2", "L2-M-X", "L9"):
        with pytest.raises(ValueError):
            kinds(bad)


def test_split_view_agrees_with_oracle():
    names = []
    for base in ("L1", "L2-R", "L2-M", "L3-R", "L3-M", "N1", "N2"):
        names.append(base)
        names += [f"{base}-{t}" for t in (*truth.ABLATIONS, *truth.COMBINED)]
    for v in names:
        assert split_view(v) == truth.split_view(v)
    for bad in ("L2-R-Z9", "Q", "L2"):
        with pytest.raises(ValueError):
            split_view(bad)
        with pytest.raises(ValueError):
            truth.split_view(bad)
    assert profiles.ABLATIONS == truth.ABLATIONS and profiles.COMBINED == truth.COMBINED
