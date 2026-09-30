import pytest
from hypothesis import given, strategies as st

from habench.campaign.compare import (
    AcmObservation, TranslationObservation, compare_acm, compare_translations, level1_sha256,
    level2_canonical, level2_sha256, levenshtein, model_versions_by_key, normalize_ws, summary_rows,
)


def test_level1_is_raw_bytes():
    assert level1_sha256(b"{}") != level1_sha256(b"{ }")


def test_level2_drops_only_top_level_metadata():
    a = {"Entities": [1], "ResponseMetadata": {"RequestId": "a"}}
    b = {"Entities": [1], "ResponseMetadata": {"RequestId": "b"}}
    assert level2_sha256(a) == level2_sha256(b)
    assert level2_canonical(a) == '{"Entities":[1]}'
    n1 = {"Entities": [{"ResponseMetadata": 1}]}
    n2 = {"Entities": [{"ResponseMetadata": 2}]}
    assert level2_sha256(n1) != level2_sha256(n2)


def test_level2_key_order_insensitive_array_order_sensitive():
    assert level2_sha256({"a": 1, "b": {"x": 1, "y": 2}}) == level2_sha256({"b": {"y": 2, "x": 1}, "a": 1})
    e1, e2 = {"Id": 0}, {"Id": 1}
    assert level2_sha256({"Entities": [e1, e2]}) != level2_sha256({"Entities": [e2, e1]})


def test_level2_floats_and_unicode_exact():
    assert level2_canonical({"s": 0.1, "t": "ção"}) == '{"s":0.1,"t":"ção"}'
    with pytest.raises(ValueError):
        level2_canonical({"s": float("nan")})


def _obs(i: int, key: str, version: str | None, l2: str | None, ok: bool = True, raw: str | None = None):
    return AcmObservation(f"c{i}", key, version, raw if raw is not None else l2, l2, ok)


def test_compare_acm_counts_and_pairs():
    obs = [_obs(0, "k", "v1", "A", raw="r1"), _obs(1, "k", "v1", "A", raw="r2"), _obs(2, "k", "v1", "B")]
    (row,) = compare_acm(obs)
    assert (row.n_ok, row.n_failed) == (3, 0)
    assert row.n_distinct_level1 == 3 and row.n_distinct_level2 == 2
    assert row.n_pairs == 3 and row.n_pairs_differing_level2 == 2


def test_version_strata_are_separate():
    obs = [_obs(0, "k", "v1", "A"), _obs(1, "k", "v1", "A"), _obs(2, "k", "v2", "B"), _obs(3, "k", "v2", "B")]
    rows = compare_acm(obs)
    assert [(r.model_version, r.n_pairs_differing_level2) for r in rows] == [("v1", 0), ("v2", 0)]
    assert model_versions_by_key(obs) == {"k": frozenset({"v1", "v2"})}


def test_failed_calls_never_distinct_content():
    obs = [_obs(0, "k", "v1", "A"), _obs(1, "k", "v1", "A"), _obs(2, "k", "v1", None, ok=False)]
    (row,) = compare_acm(obs)
    assert (row.n_ok, row.n_failed, row.n_distinct_level2, row.n_pairs_differing_level2) == (2, 1, 1, 0)
    (only_failed,) = compare_acm([_obs(0, "k", None, None, ok=False)])
    assert (only_failed.n_ok, only_failed.n_failed, only_failed.n_distinct_level1) == (0, 1, 0)
    assert model_versions_by_key([_obs(0, "k", None, None, ok=False)]) == {"k": frozenset()}


def test_ok_without_hash_rejected():
    with pytest.raises(ValueError):
        compare_acm([_obs(0, "k", "v1", None)])


def test_normalize_ws():
    assert normalize_ws("  a \t\n b  c  ") == "a b c"
    assert normalize_ws("") == ""


@pytest.mark.parametrize("a,b,d", [("", "", 0), ("abc", "", 3), ("kitten", "sitting", 3),
                                   ("flaw", "lawn", 2), ("abc", "abc", 0), ("ção", "cao", 2)])
def test_levenshtein_known(a, b, d):
    assert levenshtein(a, b) == d


def _brute(a: str, b: str) -> int:
    from functools import lru_cache

    @lru_cache(None)
    def f(i: int, j: int) -> int:
        if i == 0:
            return j
        if j == 0:
            return i
        return min(f(i - 1, j) + 1, f(i, j - 1) + 1, f(i - 1, j - 1) + (a[i - 1] != b[j - 1]))

    return f(len(a), len(b))


_text = st.text(alphabet="abc ", max_size=12)


@given(_text, _text)
def test_levenshtein_matches_brute_force_and_symmetric(a, b):
    assert levenshtein(a, b) == _brute(a, b) == levenshtein(b, a)
    assert (levenshtein(a, b) == 0) == (a == b)


@given(_text, _text, _text)
def test_levenshtein_triangle(a, b, c):
    assert levenshtein(a, c) <= levenshtein(a, b) + levenshtein(b, c)


def _t(i: int, key: str, text: str | None, ok: bool = True):
    return TranslationObservation(f"t{i}", key, text, ok)


def test_compare_translations():
    obs = [_t(0, "1|p", "hello world"), _t(1, "1|p", "hello  world"), _t(2, "1|p", "hello there"),
           _t(3, "1|p", None, ok=False)]
    (r,) = compare_translations(obs)
    assert (r.n_ok, r.n_failed, r.n_pairs) == (3, 1, 3)
    assert r.n_distinct_exact == 3 and r.n_distinct_normalized == 2
    assert r.n_pairs_differing_exact == 3 and r.n_pairs_differing_normalized == 2
    d = sorted([levenshtein("hello world", "hello  world"), levenshtein("hello world", "hello there"),
                levenshtein("hello  world", "hello there")])
    assert (r.edit_min, r.edit_median, r.edit_max) == (d[0], d[1], d[2])
    assert r.edit_mean == pytest.approx(sum(d) / 3)
    assert 0 < r.norm_edit_mean < 1


def test_translations_few_ok_and_empty():
    (r,) = compare_translations([_t(0, "k", "a"), _t(1, "k", None, ok=False)])
    assert r.n_pairs == 0 and r.edit_min is None and r.edit_mean is None and r.norm_edit_mean is None
    (r,) = compare_translations([_t(0, "k", ""), _t(1, "k", "")])
    assert r.norm_edit_mean == 0.0 and r.edit_max == 0


def test_summary_rows():
    rows = summary_rows(compare_acm([_obs(0, "k", "v", "A")]),
                        compare_translations([_t(0, "k", "a")]))
    assert [r["kind"] for r in rows] == ["acm", "translation"]
    assert rows[0]["key"] == "k"
