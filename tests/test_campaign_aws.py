import subprocess
import sys

import pytest
from botocore.exceptions import ClientError, ReadTimeoutError

from habench.campaign.aws import build_client, capture_raw_body, classify_error, http_meta, real_clients
from habench.campaign.money import PaidCallRefused

CREDS = ("AKIA" + "X" * 16, "dummy")


def test_import_does_not_load_boto():
    code = ("import habench.campaign.acm, habench.campaign.translate, habench.campaign.aws, sys;"
            "assert 'boto3' not in sys.modules and 'botocore' not in sys.modules")
    subprocess.run([sys.executable, "-c", code], check=True)


def test_build_client_disables_botocore_retries():
    client = build_client("comprehendmedical", "us-east-1", endpoint_url="http://127.0.0.1:9", credentials=CREDS,
                          read_timeout=7, connect_timeout=3)
    cfg = client.meta.config
    assert cfg.retries["total_max_attempts"] == 1
    assert cfg.read_timeout == 7 and cfg.connect_timeout == 3
    assert client.meta.endpoint_url == "http://127.0.0.1:9"
    assert client.meta.region_name == "us-east-1"


@pytest.mark.parametrize("bad", [None, object(), "auth", True])
def test_real_clients_refuses_non_authorization(bad):
    with pytest.raises(PaidCallRefused):
        real_clients(bad, "us-east-1")


def test_classify_client_error():
    exc = ClientError({"Error": {"Code": "ThrottlingException", "Message": "m"},
                       "ResponseMetadata": {"RequestId": "rid", "HTTPStatusCode": 429}}, "InferICD10CM")
    assert classify_error(exc) == ("ClientError", "ThrottlingException", "rid", 429)


def test_classify_other_exceptions():
    exc = ReadTimeoutError(endpoint_url="http://127.0.0.1:9")
    assert classify_error(exc) == ("ReadTimeoutError", "ReadTimeoutError", None, None)
    assert classify_error(ValueError("x")) == ("ValueError", "ValueError", None, None)


def test_http_meta():
    resp = {"ResponseMetadata": {"RequestId": "r", "HTTPStatusCode": 200,
                                 "HTTPHeaders": {"date": "Wed, 30 Sep 2026 12:00:00 GMT"}}}
    assert http_meta(resp) == ("r", "Wed, 30 Sep 2026 12:00:00 GMT", 200)
    assert http_meta({}) == (None, None, None)


def test_capture_raw_body_pops_and_defaults_to_none():
    client = build_client("comprehendmedical", "us-east-1", endpoint_url="http://127.0.0.1:9", credentials=CREDS)
    get = capture_raw_body(client, "after-call.comprehendmedical.InferICD10CM")
    assert get() is None

    class Http:
        content = b"raw"
        status_code = 200
        headers: dict[str, str] = {}

    client.meta.events.emit("after-call.comprehendmedical.InferICD10CM", http_response=Http(), parsed={},
                            model=None, context={})
    assert get() == b"raw"
    assert get() is None
