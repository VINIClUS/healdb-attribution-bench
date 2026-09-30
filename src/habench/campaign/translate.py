"""Bedrock Converse translation adapter (protocol §9)."""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from typing import Any

from habench.campaign.aws import capture_raw_body, classify_error, http_meta, utc_now


@dataclass(frozen=True, slots=True)
class TranslationOutcome:
    ok: bool
    started: str
    ended: str
    latency_ms: float
    region: str
    endpoint: str
    model_id: str
    temperature: float | None
    max_tokens: int
    prompt_sha256: str
    raw_body: bytes | None
    response: dict[str, Any] | None
    output_text: str | None
    stop_reason: str | None
    input_tokens: int | None
    output_tokens: int | None
    service_latency_ms: int | None
    request_id: str | None
    http_date: str | None
    http_status: int | None
    error_type: str | None
    error_code: str | None
    error_message: str | None


def converse_translate(client: Any, *, model_id: str, prompt: str, max_tokens: int,
                       temperature: float | None) -> TranslationOutcome:
    """One Converse call: user message only, no system prompt, no caching. Failures are returned, not raised."""
    inference: dict[str, Any] = {"maxTokens": max_tokens}
    if temperature is not None:
        inference["temperature"] = temperature
    pop = capture_raw_body(client, "after-call.bedrock-runtime.Converse")
    region, endpoint = client.meta.region_name, client.meta.endpoint_url
    digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    started = utc_now()
    t0 = time.perf_counter()
    try:
        response = client.converse(modelId=model_id, messages=[{"role": "user", "content": [{"text": prompt}]}],
                                   inferenceConfig=inference)
    except Exception as exc:  # noqa: BLE001 - every failure is recorded
        latency = (time.perf_counter() - t0) * 1000
        error_type, code, request_id, status = classify_error(exc)
        return TranslationOutcome(False, started, utc_now(), latency, region, endpoint, model_id, temperature,
                                  max_tokens, digest, pop(), None, None, None, None, None, None, request_id, None,
                                  status, error_type, code, str(exc))
    latency = (time.perf_counter() - t0) * 1000
    request_id, http_date, status = http_meta(response)
    blocks = response.get("output", {}).get("message", {}).get("content", [])
    text = "".join(b["text"] for b in blocks if isinstance(b, dict) and "text" in b)
    usage = response.get("usage", {})
    return TranslationOutcome(True, started, utc_now(), latency, region, endpoint, model_id, temperature,
                              max_tokens, digest, pop(), response, text, response.get("stopReason"),
                              usage.get("inputTokens"), usage.get("outputTokens"),
                              response.get("metrics", {}).get("latencyMs"), request_id, http_date, status,
                              None, None, None)
