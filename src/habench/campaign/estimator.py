"""Call counts and worst-case cost bounds for a campaign schedule (§13)."""

from collections import Counter
from dataclasses import dataclass, field

from habench.campaign.calls import (
    ACM_HEADER, ACM_TEXT_LIMIT, Condition, Schedule, ScheduledCall, Service, acm_cost_usd,
    acm_worst_case_usd, translate_worst_case_usd, translation_prompt,
)
from habench.campaign.plan import Plan

# Informative only: a token can exceed 4 characters, so this is NOT a hard bound.
CHARS_PER_TOKEN_HEURISTIC = 4


def translation_calls(n_texts: int, n_profiles: int, n_runs: int) -> int:
    return n_texts * n_profiles * n_runs


def pilot_acm_calls(n_texts: int, n_profiles: int, n_runs: int) -> int:
    """Fixed-text block plus one ACM call per propagated translation."""
    return n_texts * n_runs + translation_calls(n_texts, n_profiles, n_runs)


@dataclass(frozen=True, slots=True)
class Estimate:
    """USD figures are worst cases for one attempt per call unless named ``with_retries``."""

    counts: dict[tuple[str, str], int]  # (service, condition) -> scheduled calls
    role_counts: dict[str, int]
    usd_by_service: dict[str, float | None]  # None: some model has no price
    total_usd: float | None
    total_with_retries_usd: float | None  # x plan.retry.max_attempts
    max_call_usd: dict[tuple[str, str], float | None]  # per-call worst case by (service, condition)
    informative_full_pipeline_usd: float | None  # NOT a hard bound; None without full-pipeline calls
    missing_prices: frozenset[str]
    within_cap: bool | None  # hard-bound total with retries <= cap_usd; None if the total is unknown
    notes: tuple[str, ...] = field(default=())


def _call_worst_case(call: ScheduledCall, plan: Plan) -> tuple[float | None, str | None]:
    """Worst-case USD of one attempt and, when unpriced, the model id lacking a price."""
    if call.condition is Condition.FULL_PIPELINE:
        return acm_worst_case_usd(ACM_TEXT_LIMIT, plan.acm_price), None
    if call.input_text is None:
        raise ValueError(f"call {call.call_id!r} has no input text")
    if call.service is Service.ACM:
        return acm_cost_usd(call.input_text, plan.acm_price), None
    if call.profile is None:
        raise ValueError(f"translation call {call.call_id!r} has no profile")
    model = plan.profile(call.profile).model_id
    if plan.missing_prices({model}):
        return None, model
    return translate_worst_case_usd(translation_prompt(call.input_text), plan.max_tokens,
                                    plan.token_prices[model]), None


def _add(a: float | None, b: float | None) -> float | None:
    return None if a is None or b is None else a + b


def _max(a: float | None, b: float | None) -> float | None:
    return None if a is None or b is None else max(a, b)


def estimate(schedule: Schedule, plan: Plan) -> Estimate:
    counts: Counter[tuple[str, str]] = Counter()
    roles: Counter[str] = Counter()
    usd_by_service: dict[str, float | None] = {}
    max_call: dict[tuple[str, str], float | None] = {}
    missing: set[str] = set()
    for c in schedule.calls:
        cond = (str(c.service), str(c.condition))
        counts[cond] += 1
        roles[str(c.role)] += 1
        cost, unpriced = _call_worst_case(c, plan)
        if unpriced is not None:
            missing.add(unpriced)
        usd_by_service[cond[0]] = _add(usd_by_service.get(cond[0], 0.0), cost)
        max_call[cond] = _max(max_call.get(cond, 0.0), cost)
    total: float | None = 0.0
    for v in usd_by_service.values():
        total = _add(total, v)
    with_retries = None if total is None else total * plan.retry.max_attempts
    n_full = counts.get((str(Service.ACM), str(Condition.FULL_PIPELINE)), 0)
    informative = None
    if n_full:
        chars = min(len(ACM_HEADER) + CHARS_PER_TOKEN_HEURISTIC * plan.max_tokens, ACM_TEXT_LIMIT)
        informative = n_full * acm_worst_case_usd(chars, plan.acm_price)
    notes = [
        "full_pipeline input is unknown before collection: hard bound assumes the 10,000-character ACM limit",
        "informative full_pipeline bound assumes <= 4 characters per token and is NOT a hard bound",
        "within_cap compares the with-retries total against cap_usd and ignores spend already in the ledger",
    ]
    if missing:
        notes.append("translation cost and total are unknown: missing or placeholder prices "
                     + ", ".join(sorted(missing)))
    return Estimate(
        counts=dict(counts), role_counts=dict(roles), usd_by_service=usd_by_service, total_usd=total,
        total_with_retries_usd=with_retries, max_call_usd=max_call, informative_full_pipeline_usd=informative,
        missing_prices=frozenset(missing),
        within_cap=None if with_retries is None else with_retries <= plan.cap_usd,
        notes=tuple(notes))


def _usd(x: float | None) -> str:
    return "unknown" if x is None else f"{x:.4f}"


def format_estimate(e: Estimate) -> str:
    lines = ["calls by (service, condition):    n   max USD/call"]
    for cond in sorted(e.counts):
        lines.append(f"  {cond[0]:<10} {cond[1]:<22} {e.counts[cond]:>6}   {_usd(e.max_call_usd[cond])}")
    lines.append("calls by role: " + ", ".join(f"{r}={n}" for r, n in sorted(e.role_counts.items())))
    lines.append("worst-case USD by service (one attempt per call): "
                 + ", ".join(f"{s}={_usd(v)}" for s, v in sorted(e.usd_by_service.items())))
    lines.append(f"total USD, one attempt: {_usd(e.total_usd)}")
    lines.append(f"total USD, with retries: {_usd(e.total_with_retries_usd)}")
    if e.informative_full_pipeline_usd is not None:
        lines.append(f"informative full_pipeline USD (NOT a hard bound): {_usd(e.informative_full_pipeline_usd)}")
    if e.missing_prices:
        lines.append("missing prices: " + ", ".join(sorted(e.missing_prices)))
    lines.append(f"within cap: {e.within_cap}")
    lines.extend(f"note: {n}" for n in e.notes)
    return "\n".join(lines)
