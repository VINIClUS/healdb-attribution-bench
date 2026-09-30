import json

import pytest

from habench.historical import text_v1 as t


def _doc(*ents):
    return {"Entities": list(ents), "ResponseMetadata": {"HTTPHeaders": {"date": "Thu, 29 May 2025 03:20:50 GMT"}}}


def _ent(b, e, text, attrs=()):
    return {"BeginOffset": b, "EndOffset": e, "Text": text,
            "Attributes": [{"BeginOffset": x, "EndOffset": y, "Text": z} for x, y, z in attrs]}


def test_v1_text_duplicates_the_stripped_indication_and_cuts_in_characters():
    assert t.v1_text("  fever ") == t.P + "fever" + t.SEP + t.H + "fever"
    long = "é" * 6000
    assert len(t.v1_text(long)) == t.LIMIT


def test_check_texts_counts_spans_and_coverage():
    text = t.v1_text("fever and pain")
    b1 = len(t.P)
    b2 = len(t.P) + len("fever and pain") + len(t.SEP) + len(t.H)
    docs = {1: _doc(_ent(b1, b1 + 5, "fever"), _ent(b2 + 10, b2 + 14, "pain", [(b2, b2 + 5, "fever")])),
            2: _doc()}
    r = t.check_texts(docs, {1: text, 2: ""})
    assert (r["responses_with_entities"], r["responses_all_spans_ok"], r["spans"], r["spans_ok"]) == (1, 1, 3, 3)
    assert r["chars_covered"] == 14
    bad = t.check_texts({1: docs[1]}, {1: t.raw_text("fever and pain")})
    assert bad["responses_all_spans_ok"] == 0


def test_phases_split_on_gaps_over_one_hour():
    def d(h):
        return {"ResponseMetadata": {"HTTPHeaders": {"date": f"Thu, 29 May 2025 {h} GMT"}}}

    ph = t.phases({1: d("03:00:00"), 2: d("03:59:59"), 3: d("05:00:00"), 4: d("05:00:01")}, str)
    assert [(p["phase"], p["n"], p["ids"]) for p in ph] == [("1", 2, [1, 2]), ("2", 2, [3, 4])]


@pytest.mark.dumps
def test_committed_results_match_f1():
    r = json.loads(t.OUT_PATH.read_text(encoding="utf-8"))
    h = r["v1"]["hypotheses"]
    assert (h["v1_reconstructed"]["responses_all_spans_ok"], h["v1_reconstructed"]["spans_ok"]) == (7_189, 235_557)
    assert h["v1_reconstructed"]["spans"] == 235_557
    assert h["v1_reconstructed"]["frac_covered"] == pytest.approx(0.3695, abs=5e-5)
    assert (h["raw_indication"]["responses_all_spans_ok"], h["raw_indication"]["spans_ok"]) == (0, 78)
    assert (h["indication_only"]["responses_all_spans_ok"], h["indication_only"]["spans_ok"]) == (8, 118_871)
    assert [p["n"] for p in r["v1"]["phases"]] == [7_427, 18, 2]
    assert r["v1"]["texts_over_10000_chars"]["n"] == 20
    assert [(p["phase"], p["n"]) for p in r["v2"]["phases"]] == [("A", 7_016), ("B", 431)]
    assert r["v2"]["ds_text_submitted_check"]["spans_ok"] == r["v2"]["ds_text_submitted_check"]["spans"] == 119_302
    assert r["v2"]["submitted_equal_to_v1_reconstruction"] == 0
    assert r["translation_0327_vs_v1"] == {"identical": 7_471, "different": 2, "different_ids": [3205, 4139]}
    assert r["run_2024"]["raw_current_translation_check"]["responses_all_spans_ok"] == 7_157
    assert r["v1_md_code_system"] == {"rows": 43_194, "dotted": 38_132, "nodot_exact_in_hierarchy": 23_301}


@pytest.mark.dumps
@pytest.mark.slow
def test_committed_results_equal_fresh_computation():
    fresh = json.loads(json.dumps(t.study(), sort_keys=True, ensure_ascii=False))
    assert fresh == json.loads(t.OUT_PATH.read_text(encoding="utf-8"))
