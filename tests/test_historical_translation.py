from __future__ import annotations

import json

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from habench.data.groups import normalize_pt
from habench.historical.translation import analyze, levenshtein, levenshtein_dp, summarize


@pytest.mark.parametrize(
    "a,b,d",
    [("", "", 0), ("abc", "", 3), ("", "ab", 2), ("kitten", "sitting", 3), ("flaw", "lawn", 2),
     ("same", "same", 0), ("a", "b", 1), ("ação", "acao", 2)],
)
def test_levenshtein_small_cases(a, b, d):
    assert levenshtein_dp(a, b) == d
    assert levenshtein(a, b) == d
    assert levenshtein(b, a) == d


@settings(max_examples=300, deadline=None)
@given(st.text(alphabet="abcé ", max_size=40), st.text(alphabet="abcé ", max_size=40))
def test_bit_parallel_equals_dynamic_program(a, b):
    assert levenshtein(a, b) == levenshtein_dp(a, b)


def test_long_texts_agree():
    a = "The drug is indicated for pain. " * 60
    b = a.replace("pain", "fever", 7)[:1500] + "extra"
    assert levenshtein(a, b) == levenshtein_dp(a, b)


def test_summarize():
    s = summarize([1, 2, 3, 4, 10])
    assert (s["n"], s["min"], s["median"], s["max"]) == (5, 1.0, 3.0, 10.0)
    assert s["p90"] == pytest.approx(7.6)
    assert summarize([])["n"] == 0


def test_analyze_groups_variants_and_partitions():
    texts = {
        1: ("Dor  forte", "pain"),
        2: ("dor forte", "pain "),  # same variant after strip
        3: ("DOR FORTE", "ache"),
        4: ("febre", "fever"),
        5: ("Febre", "fever"),
        6: ("outra", "other"),
    }
    part = {1: "dev", 2: "dev", 3: "dev", 4: "test", 5: "test", 6: "reserve"}.__getitem__
    r = analyze(normalize_pt, texts, part)
    full = r["full_corpus"]
    assert full["n_groups_with_repeats"] == 2 and full["n_meds_in_groups"] == 5
    assert full["n_groups_with_distinct_english"] == 1
    assert full["distinct_english_per_group"]["max"] == 2.0
    assert full["n_english_variant_pairs"] == 1
    assert full["distance_absolute"]["max"] == levenshtein("ache", "pain")
    assert r["dev_cal"]["n_groups_with_repeats"] == 1
    assert r["other_partitions"]["n_groups_with_repeats"] == 1
    assert r["other_partitions"]["n_groups_with_distinct_english"] == 0
    # raw strip does not merge case or inner-space variants
    assert analyze(str.strip, texts, part)["full_corpus"]["n_groups_with_repeats"] == 0


@pytest.mark.dumps
def test_translation_aggregates_on_the_corpus():
    from habench.historical import translation

    r = translation.compute()
    assert r["n_medications"] == 7_447
    raw = r["by_raw_pt_strip"]["full_corpus"]
    norm = r["by_normalized_pt"]["full_corpus"]
    # F-inventory (draft, re-derived here): 469 raw-strip groups cover 1,666 medications
    assert raw["n_groups_with_repeats"] == 469 and raw["n_meds_in_groups"] == 1_666
    assert norm["n_meds_in_groups"] >= raw["n_meds_in_groups"]
    assert raw["n_groups_with_distinct_english"] > 0
    assert json.dumps(r, sort_keys=True)
    for block in ("by_normalized_pt", "by_raw_pt_strip"):
        f, d, o = (r[block][k] for k in ("full_corpus", "dev_cal", "other_partitions"))
        assert f["n_groups_with_repeats"] == d["n_groups_with_repeats"] + o["n_groups_with_repeats"]
