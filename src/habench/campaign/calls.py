"""Scheduled calls, input builders and worst-case costs shared by schedule, estimator and runner."""

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path

from habench.campaign.plan import AcmPrice, TokenPrice

# HealDB translate_leaflet_sections.py (identical at 405a10c and HEAD): no strip, cut at 6000 characters.
TRANSLATION_PROMPT = "Translate to English and return only the translation: {text}"
TRANSLATION_INPUT_LIMIT = 6000
# HealDB extract_diseases_from_indications.py @HEAD, without the drug-name masking.
ACM_HEADER = "What this medication is indicated for:\n"
ACM_TEXT_LIMIT = 10_000


class Service(StrEnum):
    ACM = "acm"
    TRANSLATE = "translate"


class Condition(StrEnum):
    SMOKE = "smoke"
    ACM_ISOLATED = "acm_isolated"  # fixed V2 submitted text
    TRANSLATION_ISOLATED = "translation_isolated"
    FULL_PIPELINE = "full_pipeline"  # ACM on the output of one translation call


class Role(StrEnum):
    REFERENCE = "reference"
    EVALUATION = "evaluation"
    SMOKE = "smoke"


def translation_prompt(pt_text: str) -> str:
    return TRANSLATION_PROMPT.format(text=pt_text[:TRANSLATION_INPUT_LIMIT])


def pipeline_acm_text(translation: str) -> str:
    return (ACM_HEADER + translation.strip() + "\n\n")[:ACM_TEXT_LIMIT]


def sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def acm_units(text: str, price: AcmPrice) -> int:
    return max(price.min_units, math.ceil(len(text) / price.unit_chars))


def acm_cost_usd(text: str, price: AcmPrice) -> float:
    return acm_units(text, price) * price.usd_per_unit


def acm_worst_case_usd(n_chars: int, price: AcmPrice) -> float:
    """Worst case for an ACM text of at most n_chars characters (the API refuses > 10,000)."""
    n = min(n_chars, ACM_TEXT_LIMIT)
    return max(price.min_units, math.ceil(n / price.unit_chars)) * price.usd_per_unit


def translate_worst_case_usd(prompt: str, max_tokens: int, price: TokenPrice) -> float:
    """UTF-8 bytes of the prompt bound the input tokens; max_tokens bounds the output."""
    return (len(prompt.encode("utf-8")) * price.input_usd_per_mtok
            + max_tokens * price.output_usd_per_mtok) / 1e6


def translate_cost_usd(input_tokens: int, output_tokens: int, price: TokenPrice) -> float:
    return (input_tokens * price.input_usd_per_mtok + output_tokens * price.output_usd_per_mtok) / 1e6


@dataclass(frozen=True, slots=True)
class ScheduledCall:
    """One planned service call. Retries of it are separate attempts with their own records.

    For FULL_PIPELINE calls the input is unknown at planning time: ``parent`` names the translation call
    whose output becomes the ACM text (pipeline_acm_text), and input_text/input_sha256 are None.
    """

    call_id: str
    block: int
    order: int  # global execution order, unique
    service: Service
    condition: Condition
    role: Role
    group_id: str
    medication: int
    repetition: int
    profile: str | None  # translation profile (TRANSLATE and FULL_PIPELINE), else None
    input_text: str | None  # PT text for TRANSLATE, ACM text for SMOKE/ACM_ISOLATED
    input_sha256: str | None
    parent: str | None


@dataclass(frozen=True, slots=True)
class Schedule:
    kind: str  # "smoke" | "pilot"
    seed: int
    plan_sha256: str
    manifest_sha256: str
    calls: tuple[ScheduledCall, ...]
    excluded: tuple[tuple[int, str], ...]  # (medication, reason) eligibility log, §4.1

    def to_json(self) -> str:
        d = asdict(self)
        return json.dumps(d, ensure_ascii=False, indent=1)

    @staticmethod
    def from_json(s: str) -> "Schedule":
        d = json.loads(s)
        calls = tuple(
            ScheduledCall(**{**c, "service": Service(c["service"]), "condition": Condition(c["condition"]),
                             "role": Role(c["role"])})
            for c in d["calls"]
        )
        return Schedule(kind=d["kind"], seed=d["seed"], plan_sha256=d["plan_sha256"],
                        manifest_sha256=d["manifest_sha256"], calls=calls,
                        excluded=tuple((int(m), str(r)) for m, r in d["excluded"]))

    def save(self, path: Path) -> None:
        path.write_text(self.to_json(), encoding="utf-8")

    @staticmethod
    def load(path: Path) -> "Schedule":
        return Schedule.from_json(path.read_text(encoding="utf-8"))
