import copy

import pytest

from habench.annotation.adjudication import (
    PendingAdjudication,
    merge,
    pending_items,
    read_adjudicated_csv,
    write_adjudicated_csv,
)
from habench.annotation.sheets import Annotation


def ann(unit, who, *codes):
    return Annotation(unit, who, frozenset(codes), "", "")


A = {"u1": ann("u1", "A", "J45", "E11"), "u2": ann("u2", "A", "I10"), "u3": ann("u3", "A", "K21")}
B = {"u1": ann("u1", "B", "J45", "N18"), "u2": ann("u2", "B", "I10"), "u4": ann("u4", "B", "C50")}


def test_pending_sorted():
    assert pending_items(A, B) == [("u1", "E11"), ("u1", "N18")]


def test_merge_requires_decisions():
    with pytest.raises(PendingAdjudication) as exc:
        merge(A, B, {("u1", "E11"): True})
    assert exc.value.items == [("u1", "N18")]


def test_merge_sources_and_no_mutation():
    a0, b0 = copy.deepcopy(A), copy.deepcopy(B)
    out = merge(A, B, {("u1", "E11"): True, ("u1", "N18"): False})
    assert A == a0 and B == b0
    assert out["u1"].codes == {"J45", "E11"}
    assert out["u1"].sources == {"J45": "agreed", "E11": "adjudicated"}
    assert out["u1"].annotators == ("A", "B")
    assert out["u2"].sources == {"I10": "agreed"}
    assert out["u3"].sources == {"K21": "single"} and out["u3"].annotators == ("A",)
    assert out["u4"].sources == {"C50": "single"} and out["u4"].annotators == ("B",)


def test_extra_decision_rejected():
    with pytest.raises(ValueError):
        merge(A, B, {("u1", "E11"): True, ("u1", "N18"): True, ("u2", "I10"): True})


def test_csv_round_trip(tmp_path):
    out = merge(A, B, {("u1", "E11"): True, ("u1", "N18"): False})
    out["u5"] = merge({"u5": ann("u5", "A")}, {}, {})["u5"]  # empty code set
    path = tmp_path / "adj.csv"
    write_adjudicated_csv(out.values(), path)
    assert read_adjudicated_csv(path) == out
