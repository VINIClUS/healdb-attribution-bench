import pytest

from habench.campaign.calls import (
    Condition, Role, Schedule, ScheduledCall, Service, translation_prompt,
)
from habench.campaign.estimator import estimate, format_estimate, pilot_acm_calls, translation_calls
from habench.campaign.plan import plan_from_dict


def _plan_dict(commercial_id: str = "m-commercial", prices: bool = True) -> dict:
    return {
        "region": "us-east-2",
        "price_source": "test",
        "acm_price": {"usd_per_unit": 0.0005, "unit_chars": 100, "min_units": 1},
        "token_prices": ({"m-commercial": {"input_usd_per_mtok": 3.0, "output_usd_per_mtok": 15.0},
                          "m-open": {"input_usd_per_mtok": 1.0, "output_usd_per_mtok": 2.0}} if prices else {}),
        "profiles": [{"name": "commercial", "model_id": commercial_id, "temperature": None},
                     {"name": "open_weights", "model_id": "m-open", "temperature": None}],
        "max_tokens": 1000,
        "cap_usd": 30.0,
        "retry": {"max_attempts": 3, "backoff_s": 1.0, "retryable": ["ThrottlingException"]},
        "block_spacing_s": 0,
        "seed": 1,
        "smoke": {"texts": 2, "repetitions": 2},
        "pilot": {"texts": 2, "repetitions": 4, "references": 2, "blocks": 2},
    }


def _call(i: int, service: Service, condition: Condition, text: str | None, profile: str | None = None) -> ScheduledCall:
    return ScheduledCall(call_id=f"c{i}", block=0, order=i, service=service, condition=condition,
                         role=Role.EVALUATION, group_id="g", medication=1, repetition=i, profile=profile,
                         input_text=text, input_sha256=None, parent=None)


def _schedule(*calls: ScheduledCall) -> Schedule:
    return Schedule(kind="pilot", seed=1, plan_sha256="p", manifest_sha256="m", calls=calls, excluded=())


def test_section_13_examples():
    assert translation_calls(150, 3, 5) == 2250
    assert translation_calls(60, 3, 10) == 1800
    assert pilot_acm_calls(60, 3, 10) == 600 + 1800 == 2400


def test_estimate_priced():
    text = "x" * 250  # 3 ACM units
    pt = "y" * 10
    sched = _schedule(
        _call(0, Service.ACM, Condition.ACM_ISOLATED, text),
        _call(1, Service.TRANSLATE, Condition.TRANSLATION_ISOLATED, pt, "commercial"),
        _call(2, Service.TRANSLATE, Condition.TRANSLATION_ISOLATED, pt, "open_weights"),
        _call(3, Service.ACM, Condition.FULL_PIPELINE, None, "commercial"),
    )
    e = estimate(sched, plan_from_dict(_plan_dict()))
    n_in = len(translation_prompt(pt).encode())
    tr = (n_in * 3.0 + 1000 * 15.0) / 1e6 + (n_in * 1.0 + 1000 * 2.0) / 1e6
    assert e.counts[("acm", "acm_isolated")] == 1
    assert e.counts[("acm", "full_pipeline")] == 1
    assert e.role_counts == {"evaluation": 4}
    assert e.usd_by_service["acm"] == pytest.approx(3 * 0.0005 + 0.05)
    assert e.usd_by_service["translate"] == pytest.approx(tr)
    assert e.total_usd == pytest.approx(3 * 0.0005 + 0.05 + tr)
    assert e.total_with_retries_usd == pytest.approx(3 * e.total_usd)
    assert e.max_call_usd[("acm", "full_pipeline")] == pytest.approx(0.05)
    assert e.missing_prices == frozenset()
    assert e.within_cap is True
    # informative: 39 + 4000 chars -> 41 units, never the hard bound
    assert e.informative_full_pipeline_usd == pytest.approx(41 * 0.0005)
    assert "NOT a hard bound" in format_estimate(e)


def test_full_pipeline_costs_005_each():
    e = estimate(_schedule(*[_call(i, Service.ACM, Condition.FULL_PIPELINE, None, "commercial") for i in range(4)]),
                 plan_from_dict(_plan_dict()))
    assert e.total_usd == pytest.approx(0.2)


def test_placeholder_prices_yield_none():
    sched = _schedule(
        _call(0, Service.ACM, Condition.ACM_ISOLATED, "abc"),
        _call(1, Service.TRANSLATE, Condition.TRANSLATION_ISOLATED, "yy", "commercial"),
    )
    e = estimate(sched, plan_from_dict(_plan_dict("<MODEL_ID_COMMERCIAL>")))
    assert e.missing_prices == frozenset({"<MODEL_ID_COMMERCIAL>"})
    assert e.usd_by_service["translate"] is None
    assert e.usd_by_service["acm"] == pytest.approx(0.0005)
    assert e.total_usd is None and e.total_with_retries_usd is None
    assert e.within_cap is None


def test_unlisted_model_is_missing():
    e = estimate(_schedule(_call(0, Service.TRANSLATE, Condition.TRANSLATION_ISOLATED, "yy", "commercial")),
                 plan_from_dict(_plan_dict(prices=False)))
    assert e.missing_prices == frozenset({"m-commercial"})
    assert e.total_usd is None


def test_over_cap_uses_retries():
    d = _plan_dict()
    d["cap_usd"] = 0.2  # one attempt 0.15 fits, three attempts do not
    e = estimate(_schedule(*[_call(i, Service.ACM, Condition.FULL_PIPELINE, None) for i in range(3)]),
                 plan_from_dict(d))
    assert e.total_usd == pytest.approx(0.15)
    assert e.within_cap is False


def test_translation_input_cut_at_limit():
    long_pt = "z" * 9000
    e = estimate(_schedule(_call(0, Service.TRANSLATE, Condition.TRANSLATION_ISOLATED, long_pt, "open_weights")),
                 plan_from_dict(_plan_dict()))
    n_in = len(translation_prompt(long_pt).encode())
    assert n_in < 9000
    assert e.total_usd == pytest.approx((n_in * 1.0 + 1000 * 2.0) / 1e6)
