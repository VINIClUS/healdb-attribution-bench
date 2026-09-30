"""Amazon Comprehend Medical InferICD10CM adapter (protocol §9)."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from habench.campaign.aws import capture_raw_body, classify_error, http_meta, utc_now

MAX_CHARS = 10_000  # API contract for InferICD10CM


@dataclass(frozen=True, slots=True)
class AcmOutcome:
    ok: bool
    started: str
    ended: str
    latency_ms: float
    region: str
    endpoint: str
    input_chars: int
    raw_body: bytes | None
    response: dict[str, Any] | None
    model_version: str | None
    request_id: str | None
    http_date: str | None
    http_status: int | None
    error_type: str | None
    error_code: str | None
    error_message: str | None


def infer_icd10_cm(client: Any, text: str) -> AcmOutcome:
    """One InferICD10CM call. Never raises on service or transport errors; never fabricates an empty response."""
    if not text or len(text) > MAX_CHARS:
        raise ValueError(f"text must have 1..{MAX_CHARS} characters, got {len(text)}")
    pop = capture_raw_body(client, "after-call.comprehendmedical.InferICD10CM")
    region, endpoint = client.meta.region_name, client.meta.endpoint_url
    started = utc_now()
    t0 = time.perf_counter()
    try:
        response = client.infer_icd10_cm(Text=text)
    except Exception as exc:  # noqa: BLE001 - every failure is recorded, none becomes an empty result
        latency = (time.perf_counter() - t0) * 1000
        error_type, code, request_id, status = classify_error(exc)
        return AcmOutcome(False, started, utc_now(), latency, region, endpoint, len(text), pop(), None, None,
                          request_id, None, status, error_type, code, str(exc))
    latency = (time.perf_counter() - t0) * 1000
    request_id, http_date, status = http_meta(response)
    return AcmOutcome(True, started, utc_now(), latency, region, endpoint, len(text), pop(), response,
                      response.get("ModelVersion"), request_id, http_date, status, None, None, None)
