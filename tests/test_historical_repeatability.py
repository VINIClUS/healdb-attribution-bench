from __future__ import annotations

import json

import pytest

from habench.historical import repeatability as R


def resp(entities=(), date="Thu, 29 May 2025 10:00:00 GMT", version="3.0", request_id="x"):
    return json.dumps({
        "Entities": list(entities), "ModelVersion": version,
        "ResponseMetadata": {"RequestId": request_id, "HTTPHeaders": {"date": date}},
    })


def ent(code="A01", score=0.9):
    return {"Id": 0, "Score": 0.9, "Type": "DX_NAME", "Traits": [],
            "ICD10CMConcepts": [{"Code": code, "Score": score}]}


@pytest.mark.parametrize("k,n", [(0, 1), (0, 10), (0, 197), (1, 10), (3, 40), (5, 5), (17, 200), (0, 2), (30, 31)])
def test_clopper_pearson_matches_scipy(k, n):
    from scipy.stats import beta

    want = 1.0 if k == n else float(beta.ppf(0.95, k + 1, n - k))
    assert R.clopper_pearson_upper(k, n) == pytest.approx(want, abs=1e-9)


def test_clopper_pearson_zero_closed_form_and_errors():
    assert R.clopper_pearson_upper(0, 197) == pytest.approx(1 - 0.05 ** (1 / 197))
    with pytest.raises(ValueError):
        R.clopper_pearson_upper(3, 2)
    with pytest.raises(ValueError):
        R.clopper_pearson_upper(0, 0)


def test_v1_text_reconstruction_and_cut():
    assert R.v1_text("  drug X \n") == "What this medication is indicated for:\ndrug X\n\nHow this medication works:\ndrug X"
    long = "a" * 9000
    assert len(R.v1_text(long)) == 10_000


def test_phase_labels_v1_numbers_v2_letters():
    assert R.phase_labels("v1", {1: 1, 2: 3, 3: 0}) == {1: "1", 2: "3", 3: "none"}
    assert R.phase_labels("v2", {1: 1, 2: 2}) == {1: "A", 2: "B"}


def test_phase_gap_over_one_hour_starts_new_phase_in_analysis():
    t = {1: "same", 2: "same", 3: "same", 4: "same"}
    r = {
        1: resp([ent()], "Thu, 29 May 2025 10:00:00 GMT"),
        2: resp([ent()], "Thu, 29 May 2025 10:59:00 GMT", request_id="y"),  # transport metadata only
        3: resp([ent()], "Thu, 29 May 2025 13:00:00 GMT"),
        4: resp([ent("B02")], "Thu, 29 May 2025 13:01:00 GMT"),
    }
    out = R.analyze_run("v2", t, r, "armazenado", "test")
    assert out["phase_sizes"] == {"A": 2, "B": 2}
    assert out["overall"]["n_texts_with_repeats"] == 1
    assert out["overall"]["n_meds_in_groups"] == 4 and out["overall"]["n_pairs"] == 6
    assert out["overall"]["n_groups_differing"] == 1 and out["overall"]["n_pairs_differing"] == 3
    assert out["cross_phase"]["n_texts_with_repeats"] == 1
    assert out["by_phase_all_members_in_phase"]["A"]["n_texts_with_repeats"] == 0
    assert out["pairs_by_phase_pair"] == {
        "A-A": {"n_pairs": 1, "n_pairs_differing": 0},
        "A-B": {"n_pairs": 4, "n_pairs_differing": 2},
        "B-B": {"n_pairs": 1, "n_pairs_differing": 1},
    }


def test_identical_texts_equal_responses_and_bound():
    t = {m: "same" for m in range(1, 5)} | {9: "unique", 10: None}
    d = "Thu, 29 May 2025 10:00:00 GMT"
    r = {1: resp([ent()], d, request_id="a"), 2: resp([ent()], d, request_id="b"), 3: resp([ent()], d),
         4: resp([ent()], d), 9: resp([], d), 10: resp([], d), 11: None, 12: "{not json"}
    out = R.analyze_run("v1", t, r, "inferido_compativel", "test")
    o = out["overall"]
    assert (o["n_texts_with_repeats"], o["n_meds_in_groups"], o["n_pairs"]) == (1, 4, 6)
    assert o["n_groups_differing"] == 0 and o["n_pairs_differing"] == 0
    assert o["upper95_differing_group_fraction"] == pytest.approx(0.95)
    assert out["n_responses_excluded_failed"] == 2 and out["n_excluded_without_text"] == 1
    assert out["model_versions"] == {"3.0": 6}
    assert out["by_phase_all_members_in_phase"]["1"]["n_texts_with_repeats"] == 1


def test_model_version_difference_counts_as_level2_difference():
    t = {1: "same", 2: "same"}
    d = "Thu, 29 May 2025 10:00:00 GMT"
    out = R.analyze_run("g0327", t, {1: resp([ent()], d, version="2.7"), 2: resp([ent()], d, version="3.0")}, "x", "y")
    assert out["overall"]["n_groups_differing"] == 1


def test_attribute_order_differences_are_counted_but_diagnosed():
    d = "Thu, 29 May 2025 10:00:00 GMT"
    e1, e2 = ent(), ent()
    e1["Attributes"] = [{"Text": "acute"}, {"Text": "chronic"}]
    e2["Attributes"] = [{"Text": "chronic"}, {"Text": "acute"}]
    out = R.analyze_run("g0327", {1: "same", 2: "same"}, {1: resp([e1], d), 2: resp([e2], d)}, "x", "y")
    assert out["overall"]["n_groups_differing"] == 1  # level 2 keeps array order
    assert out["differing_groups_attribute_order_only"] == 1


@pytest.mark.dumps
def test_corpus_runs_have_expected_shape():
    out = R.compute()
    assert set(out) == {"v1", "v2", "g0327"}
    assert out["v1"]["text_state"] == "inferido_compativel" and out["v2"]["text_state"] == "armazenado"
    assert out["v2"]["phase_sizes"] == {"A": 7_016, "B": 431}
    for r in out.values():
        o = r["overall"]
        assert o["n_texts_with_repeats"] > 0
        assert o["n_groups_differing"] <= o["n_texts_with_repeats"]
        assert 0.0 <= o["upper95_differing_group_fraction"] <= 1.0
