import copy
from pathlib import Path

import pytest
import yaml

from habench.campaign.calls import (
    ACM_TEXT_LIMIT,
    Condition,
    Role,
    Schedule,
    ScheduledCall,
    Service,
    acm_cost_usd,
    acm_units,
    acm_worst_case_usd,
    pipeline_acm_text,
    translate_worst_case_usd,
    translation_prompt,
)
from habench.campaign.plan import PlanError, TokenPrice, is_placeholder, load_plan, plan_from_dict

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "repro" / "campaign_plan.template.yaml"


def test_template_loads_with_placeholders_and_no_prices():
    plan = load_plan(TEMPLATE)
    assert plan.region == "us-east-2"
    assert plan.cap_usd == 30.0
    assert [p.name for p in plan.profiles] == ["commercial", "commercial_t0", "open_weights"]
    assert plan.profile("commercial_t0").temperature == 0.0
    assert plan.profile("commercial").temperature is None
    assert all(is_placeholder(p.model_id) for p in plan.profiles)
    assert plan.missing_prices({p.model_id for p in plan.profiles}) == {p.model_id for p in plan.profiles}
    assert (plan.pilot_texts, plan.pilot_repetitions, plan.pilot_references) == (60, 10, 6)
    assert (plan.smoke_texts, plan.smoke_repetitions) == (20, 5)


def test_plan_validation():
    d = yaml.safe_load(TEMPLATE.read_text(encoding="utf-8"))
    for mutate, msg in [
        (lambda x: x.pop("cap_usd"), "cap_usd"),
        (lambda x: x["pilot"].update(references=10), "references"),
        (lambda x: x["retry"].update(max_attempts=0), "max_attempts"),
        (lambda x: x["profiles"].append(dict(x["profiles"][0])), "duplicate"),
    ]:
        dd = copy.deepcopy(d)
        mutate(dd)
        with pytest.raises(PlanError, match=msg):
            plan_from_dict(dd)


def test_acm_units_and_cost():
    price = load_plan(TEMPLATE).acm_price
    assert acm_units("", price) == 1
    assert acm_units("x" * 100, price) == 1
    assert acm_units("x" * 101, price) == 2
    assert acm_cost_usd("x" * 10_000, price) == pytest.approx(0.05)
    assert acm_worst_case_usd(50_000, price) == pytest.approx(0.05)  # the API refuses > 10,000 characters


def test_translation_prompt_is_historical_and_unstripped():
    pt = " Abba, em combinação" + "x" * 7000
    p = translation_prompt(pt)
    assert p == "Translate to English and return only the translation: " + pt[:6000]
    assert p.startswith("Translate to English and return only the translation:  Abba")


def test_pipeline_acm_text():
    assert pipeline_acm_text("  Abba is indicated. \n") == "What this medication is indicated for:\nAbba is indicated.\n\n"
    assert len(pipeline_acm_text("y" * 20_000)) == ACM_TEXT_LIMIT


def test_translate_worst_case_uses_bytes_and_max_tokens():
    price = TokenPrice(input_usd_per_mtok=1.0, output_usd_per_mtok=4.0)
    prompt = "ção"  # 5 UTF-8 bytes
    assert translate_worst_case_usd(prompt, 1000, price) == pytest.approx((5 * 1.0 + 1000 * 4.0) / 1e6)


def test_schedule_json_round_trip(tmp_path):
    calls = (
        ScheduledCall("c1", 0, 0, Service.TRANSLATE, Condition.TRANSLATION_ISOLATED, Role.REFERENCE, "g1", 4, 0,
                      "commercial", " texto", "abc", None),
        ScheduledCall("c2", 0, 1, Service.ACM, Condition.FULL_PIPELINE, Role.REFERENCE, "g1", 4, 0,
                      "commercial", None, None, "c1"),
    )
    s = Schedule("pilot", 7, "p", "m", calls, ((9, "empty PT indication"),))
    s.save(tmp_path / "s.json")
    assert Schedule.load(tmp_path / "s.json") == s
