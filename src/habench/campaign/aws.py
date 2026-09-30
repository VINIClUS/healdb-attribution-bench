"""Thin, lazily imported boto3 helpers for the Study C campaign.

boto3/botocore are imported inside functions only. Botocore's own retries are disabled: the caller's retry policy
(and the money ledger) must see every HTTP request.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from habench.campaign.money import PaidAuthorization, PaidCallRefused
from habench.prov.records import utc_now

__all__ = ["build_client", "capture_raw_body", "classify_error", "http_meta", "real_clients", "utc_now"]


def build_client(service: str, region: str, *, endpoint_url: str | None = None,
                 credentials: tuple[str, str] | None = None, read_timeout: float = 120,
                 connect_timeout: float = 10) -> Any:
    """Low-level client factory; exactly one HTTP request per API call (no botocore retries)."""
    import boto3
    from botocore.config import Config

    config = Config(retries={"total_max_attempts": 1, "mode": "standard"}, read_timeout=read_timeout,
                    connect_timeout=connect_timeout)
    if credentials is not None:
        session = boto3.session.Session(aws_access_key_id=credentials[0], aws_secret_access_key=credentials[1],
                                        region_name=region)
    else:
        session = boto3.session.Session(region_name=region)
    return session.client(service, region_name=region, endpoint_url=endpoint_url, config=config)


def real_clients(auth: PaidAuthorization, region: str) -> tuple[Any, Any]:
    """Production (ACM, Bedrock runtime) clients; only reachable with a PaidAuthorization."""
    if not isinstance(auth, PaidAuthorization):
        raise PaidCallRefused("real AWS clients require a PaidAuthorization from authorize_paid()")
    return build_client("comprehendmedical", region), build_client("bedrock-runtime", region)


def capture_raw_body(client: Any, operation_event: str) -> Callable[[], bytes | None]:
    """Record the raw HTTP body of the latest call; the getter pops it (None when not captured).

    The handler is registered once per client and event; later calls reuse the same getter.
    """
    getters = client.__dict__.setdefault("_habench_raw_body_getters", {})
    if operation_event in getters:
        return getters[operation_event]
    box: list[bytes] = []

    def handler(http_response: Any = None, **_: Any) -> None:
        box.clear()
        content = getattr(http_response, "content", None)
        if isinstance(content, bytes):
            box.append(content)

    client.meta.events.register(operation_event, handler)

    def pop() -> bytes | None:
        return box.pop() if box else None

    getters[operation_event] = pop
    return pop


def classify_error(exc: BaseException) -> tuple[str, str, str | None, int | None]:
    """(error_type, error_code, request_id, http_status)."""
    from botocore.exceptions import ClientError

    if isinstance(exc, ClientError):
        meta = exc.response.get("ResponseMetadata", {})
        code = str(exc.response.get("Error", {}).get("Code", "")) or type(exc).__name__
        return "ClientError", code, meta.get("RequestId"), meta.get("HTTPStatusCode")
    return type(exc).__name__, type(exc).__name__, None, None


def http_meta(response: dict[str, Any]) -> tuple[str | None, str | None, int | None]:
    """(request_id, http_date, http_status) from ResponseMetadata."""
    meta = response.get("ResponseMetadata", {})
    headers = meta.get("HTTPHeaders", {})
    date = next((v for k, v in headers.items() if k.lower() == "date"), None)
    return meta.get("RequestId"), date, meta.get("HTTPStatusCode")
