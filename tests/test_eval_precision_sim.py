import pytest

from habench.eval.precision_sim import simulate_power

KW = dict(replicas=50, B=100)


def test_deterministic_bounded():
    a = simulate_power([1, 2, 3], [2, 4], 0.3, n_grid=(50, 100), **KW)
    b = simulate_power([1, 2, 3], [2, 4], 0.3, n_grid=(50, 100), **KW)
    assert a == b
    assert a.n_grid == (50, 100)
    assert all(0.0 <= p <= 1.0 for p in a.power)


def test_power_grows_with_n_and_smallest_n():
    r = simulate_power([2, 3, 4], [4, 6], 0.1, n_grid=(20, 2000), replicas=60, B=100)
    assert r.power[1] >= r.power[0]
    assert r.power[1] >= 0.8
    assert r.smallest_n in (20, 2000)


def test_none_when_unreachable():
    r = simulate_power([1], [1], 0.5, n_grid=(10,), replicas=30, B=50, target=1.01)
    assert r.smallest_n is None


def test_validation():
    with pytest.raises(ValueError):
        simulate_power([], [1], 0.1, n_grid=(10,), **KW)
    with pytest.raises(ValueError):
        simulate_power([1], [1], 1.0, n_grid=(10,), **KW)
