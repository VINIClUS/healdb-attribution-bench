import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from habench.annotation.sampler import (
    SampledUnit,
    Unit,
    allocate,
    check_disjoint,
    draw_evaluation,
    draw_pilot,
    horvitz_thompson_mean,
    read_sample_csv,
    write_sample_csv,
)


def make_frame(sizes: dict[str, int]) -> list[Unit]:
    return [Unit(f"{s}-{i:03d}", f"g-{s}-{i:03d}", s) for s, k in sizes.items() for i in range(k)]


def test_pilot_basic():
    frame = make_frame({"a": 30, "b": 30})
    pilot = draw_pilot(frame, 20, seed=1)
    assert len(pilot) == 20
    assert len({u.unit_id for u in pilot}) == 20
    assert all(u.phase == "pilot" and u.pi1 == pytest.approx(20 / 60) and not u.double for u in pilot)
    assert all(u.weight == pytest.approx(3.0) and u.pi2 is None and u.pi_double is None for u in pilot)


def test_input_order_irrelevant_and_deterministic():
    frame = make_frame({"a": 40, "b": 20, "c": 10})
    assert draw_evaluation(frame, 30, 10, seed=5) == draw_evaluation(frame[::-1], 30, 10, seed=5)
    assert draw_pilot(frame, 5, seed=5) == draw_pilot(frame[::-1], 5, seed=5)
    assert draw_pilot(frame, 5, seed=5) != draw_pilot(frame, 5, seed=6)


def test_evaluation_allocation_and_probabilities():
    frame = make_frame({"a": 60, "b": 30, "c": 10})
    sample = draw_evaluation(frame, 20, 8, seed=3)
    counts = {s: sum(u.stratum == s for u in sample) for s in "abc"}
    assert counts == {"a": 12, "b": 6, "c": 2}
    assert sum(u.double for u in sample) == 8
    for u in sample:
        assert u.pi1 == pytest.approx(counts[u.stratum] / {"a": 60, "b": 30, "c": 10}[u.stratum])
        assert u.weight == pytest.approx(1 / u.pi1)
        assert u.pi2 == pytest.approx(8 / 20)
        assert u.pi_double == pytest.approx(u.pi1 * 8 / 20)
        assert u.phase == "evaluation"
    # weights sum to the frame size (proportional allocation)
    assert sum(u.weight for u in sample) == pytest.approx(100)


def test_largest_remainder_ties_by_name():
    # 3 equal strata, n=1: every remainder ties, so the alphabetically first stratum wins
    assert allocate({"c": 10, "a": 10, "b": 10}, 1) == {"a": 1, "b": 0, "c": 0}
    assert allocate({"c": 10, "a": 10, "b": 10}, 2) == {"a": 1, "b": 1, "c": 0}


def test_allocation_caps_and_redistributes():
    # n == N forces every stratum to be fully included
    assert allocate({"a": 1, "b": 5, "c": 2}, 8) == {"a": 1, "b": 5, "c": 2}


@given(
    sizes=st.dictionaries(st.text("abcdef", min_size=1, max_size=3), st.integers(1, 40), min_size=1, max_size=6),
    data=st.data(),
)
@settings(max_examples=100, deadline=None)
def test_allocation_properties(sizes, data):
    n = data.draw(st.integers(0, sum(sizes.values())))
    alloc = allocate(sizes, n)
    assert sum(alloc.values()) == n
    assert all(0 <= alloc[s] <= sizes[s] for s in sizes)
    total = sum(sizes.values())
    # proportional up to rounding
    assert all(abs(alloc[s] - n * sizes[s] / total) < 1 for s in sizes)


def test_exclude_groups_and_errors():
    frame = make_frame({"a": 30, "b": 30})
    excluded = {u.group_id for u in frame[:10]}
    sample = draw_evaluation(frame, 20, 5, seed=2, exclude_groups=excluded)
    assert not {u.group_id for u in sample} & excluded
    with pytest.raises(ValueError):
        draw_evaluation(frame, 55, 5, seed=2, exclude_groups=excluded)  # 50 left
    with pytest.raises(ValueError):
        draw_pilot(frame, 61, seed=1)
    with pytest.raises(ValueError):
        draw_evaluation(frame, 10, 11, seed=1)
    with pytest.raises(ValueError, match="unique"):
        draw_pilot([*frame, frame[0]], 5, seed=1)


def test_check_disjoint():
    frame = make_frame({"a": 30})
    pilot = draw_pilot(frame, 5, seed=1)
    with pytest.raises(ValueError, match="share groups"):
        check_disjoint(pilot, frame)
    rest = [u for u in frame if u.group_id not in {p.group_id for p in pilot}]
    check_disjoint(pilot, rest)


def test_csv_round_trip(tmp_path):
    frame = make_frame({"a": 30, "b": 20})
    units = draw_pilot(frame, 5, seed=1) + draw_evaluation(frame, 20, 7, seed=1)
    path = tmp_path / "s.csv"
    write_sample_csv(units, path)
    assert read_sample_csv(path) == units


def test_horvitz_thompson_mean():
    sample = [
        SampledUnit("x", "g1", "a", "evaluation", 0.5, 2.0, False, None, None),
        SampledUnit("y", "g2", "b", "evaluation", 0.25, 4.0, False, None, None),
    ]
    assert horvitz_thompson_mean({"x": 1.0, "y": 0.0}, sample) == pytest.approx(2 / 6)
    with pytest.raises(ValueError):
        horvitz_thompson_mean({"x": 1.0}, sample)
