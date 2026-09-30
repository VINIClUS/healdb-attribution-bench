"""Campaign plan file (repro/campaign_plan.template.yaml): region, profiles, prices, cap, retries, blocks.

Prices live in the plan, never in code. Model ids written as ``<...>`` are placeholders and have no price.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


class PlanError(ValueError):
    """The plan file is malformed or incomplete."""


def is_placeholder(model_id: str) -> bool:
    return model_id.startswith("<") and model_id.endswith(">")


@dataclass(frozen=True, slots=True)
class Profile:
    """A translation profile (§9.2). temperature None means the service default (not sent)."""

    name: str
    model_id: str
    temperature: float | None


@dataclass(frozen=True, slots=True)
class AcmPrice:
    """InferICD10CM: max(min_units, ceil(chars / unit_chars)) units × usd_per_unit."""

    usd_per_unit: float
    unit_chars: int
    min_units: int


@dataclass(frozen=True, slots=True)
class TokenPrice:
    """Bedrock on-demand price per million tokens."""

    input_usd_per_mtok: float
    output_usd_per_mtok: float


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Runner-level retries; botocore's own retries are always disabled."""

    max_attempts: int
    backoff_s: float
    retryable: tuple[str, ...]  # error codes, e.g. ThrottlingException


@dataclass(frozen=True, slots=True)
class Plan:
    region: str
    acm_price: AcmPrice
    token_prices: dict[str, TokenPrice]  # keyed by model id
    profiles: tuple[Profile, ...]
    max_tokens: int
    cap_usd: float  # cumulative across runs, whole ledger
    retry: RetryPolicy
    block_spacing_s: float  # minimum wait between the starts of consecutive temporal blocks
    seed: int
    smoke_texts: int
    smoke_repetitions: int
    pilot_texts: int
    pilot_repetitions: int
    pilot_references: int  # per text/profile; the rest are evaluation realizations
    pilot_blocks: int
    price_source: str

    def profile(self, name: str) -> Profile:
        for p in self.profiles:
            if p.name == name:
                return p
        raise PlanError(f"unknown profile {name!r}")

    def missing_prices(self, model_ids: set[str]) -> set[str]:
        """Model ids with no usable price entry (placeholders never have one)."""
        return {m for m in model_ids if is_placeholder(m) or m not in self.token_prices}


def _req(d: dict[str, Any], key: str, where: str) -> Any:
    if key not in d:
        raise PlanError(f"missing {where}.{key}")
    return d[key]


def plan_from_dict(d: dict[str, Any]) -> Plan:
    acm = _req(d, "acm_price", "plan")
    retry = _req(d, "retry", "plan")
    pilot = _req(d, "pilot", "plan")
    smoke = _req(d, "smoke", "plan")
    profiles = tuple(
        Profile(name=str(_req(p, "name", "profiles[]")), model_id=str(_req(p, "model_id", "profiles[]")),
                temperature=None if p.get("temperature") is None else float(p["temperature"]))
        for p in _req(d, "profiles", "plan")
    )
    if len({p.name for p in profiles}) != len(profiles):
        raise PlanError("duplicate profile names")
    plan = Plan(
        region=str(_req(d, "region", "plan")),
        acm_price=AcmPrice(usd_per_unit=float(_req(acm, "usd_per_unit", "acm_price")),
                           unit_chars=int(_req(acm, "unit_chars", "acm_price")),
                           min_units=int(_req(acm, "min_units", "acm_price"))),
        token_prices={
            str(m): TokenPrice(input_usd_per_mtok=float(_req(v, "input_usd_per_mtok", f"token_prices[{m}]")),
                               output_usd_per_mtok=float(_req(v, "output_usd_per_mtok", f"token_prices[{m}]")))
            for m, v in (d.get("token_prices") or {}).items()
        },
        profiles=profiles,
        max_tokens=int(_req(d, "max_tokens", "plan")),
        cap_usd=float(_req(d, "cap_usd", "plan")),
        retry=RetryPolicy(max_attempts=int(_req(retry, "max_attempts", "retry")),
                          backoff_s=float(_req(retry, "backoff_s", "retry")),
                          retryable=tuple(str(c) for c in _req(retry, "retryable", "retry"))),
        block_spacing_s=float(_req(d, "block_spacing_s", "plan")),
        seed=int(_req(d, "seed", "plan")),
        smoke_texts=int(_req(smoke, "texts", "smoke")),
        smoke_repetitions=int(_req(smoke, "repetitions", "smoke")),
        pilot_texts=int(_req(pilot, "texts", "pilot")),
        pilot_repetitions=int(_req(pilot, "repetitions", "pilot")),
        pilot_references=int(_req(pilot, "references", "pilot")),
        pilot_blocks=int(_req(pilot, "blocks", "pilot")),
        price_source=str(_req(d, "price_source", "plan")),
    )
    if plan.retry.max_attempts < 1:
        raise PlanError("retry.max_attempts must be >= 1")
    if not 0 < plan.pilot_references < plan.pilot_repetitions:
        raise PlanError("pilot.references must be in (0, repetitions)")
    if plan.pilot_blocks < 1 or plan.pilot_blocks > plan.pilot_repetitions:
        raise PlanError("pilot.blocks must be in [1, repetitions]")
    if plan.cap_usd <= 0:
        raise PlanError("cap_usd must be positive")
    return plan


def load_plan(path: Path) -> Plan:
    with open(path, encoding="utf-8") as f:
        return plan_from_dict(yaml.safe_load(f))
