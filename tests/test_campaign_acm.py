import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from habench.campaign.acm import infer_icd10_cm
from habench.campaign.aws import build_client

CREDS = ("AKIA" + "X" * 16, "dummy")

BODY = json.dumps({
    "Entities": [{"Id": 0, "Text": "diabetes", "Category": "MEDICAL_CONDITION", "Type": "DX_NAME", "Score": 0.98,
                  "BeginOffset": 0, "EndOffset": 8, "Traits": [],
                  "ICD10CMConcepts": [{"Description": "Type 2 diabetes mellitus", "Code": "E11.9", "Score": 0.9}]}],
    "PaginationToken": None, "ModelVersion": "3.2.0.20251001",
}).encode()


@contextmanager
def fake_server(status: int, body: bytes, headers: dict[str, str] | None = None):
    received: list[tuple[str, dict[str, str], bytes]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            data = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            received.append((self.path, dict(self.headers), data))
            self.send_response_only(status)  # no automatic Server/Date headers
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", received
    finally:
        server.shutdown()
        server.server_close()


def client_for(url: str):
    return build_client("comprehendmedical", "us-east-1", endpoint_url=url, credentials=CREDS)


def test_success_keeps_exact_body_and_metadata():
    headers = {"Content-Type": "application/x-amz-json-1.1", "x-amzn-RequestId": "req-123",
               "Date": "Wed, 30 Sep 2026 12:00:00 GMT"}
    with fake_server(200, BODY, headers) as (url, received):
        out = infer_icd10_cm(client_for(url), "patient has diabetes")
    assert len(received) == 1
    _, hdrs, data = received[0]
    assert json.loads(data) == {"Text": "patient has diabetes"}
    assert hdrs["X-Amz-Target"] == "ComprehendMedical_20181030.InferICD10CM"
    assert out.ok and out.raw_body == BODY
    assert out.response["Entities"][0]["ICD10CMConcepts"][0]["Code"] == "E11.9"
    assert out.response["ResponseMetadata"]["HTTPStatusCode"] == 200
    assert out.model_version == "3.2.0.20251001"
    assert out.request_id == "req-123"
    assert out.http_date == "Wed, 30 Sep 2026 12:00:00 GMT"
    assert out.http_status == 200
    assert out.input_chars == 20 and out.region == "us-east-1" and out.endpoint == url
    assert out.error_code is None and out.latency_ms >= 0 and out.started <= out.ended


def test_repeated_calls_on_one_client_reuse_one_body_handler():
    headers = {"Content-Type": "application/x-amz-json-1.1"}
    with fake_server(200, BODY, headers) as (url, received):
        client = client_for(url)
        outs = [infer_icd10_cm(client, "patient has diabetes") for _ in range(3)]
    assert len(received) == 3
    assert all(o.ok and o.raw_body == BODY for o in outs)
    assert list(client.__dict__["_habench_raw_body_getters"]) == ["after-call.comprehendmedical.InferICD10CM"]


def test_http_500_is_one_request_and_a_failure():
    with fake_server(500, b'{"__type": "InternalServerException", "message": "boom"}',
                     {"Content-Type": "application/x-amz-json-1.1"}) as (url, received):
        out = infer_icd10_cm(client_for(url), "text")
    assert len(received) == 1  # botocore retries are off
    assert not out.ok and out.response is None and out.model_version is None
    assert out.error_code == "InternalServerException"
    assert out.http_status == 500


def test_throttling_429_is_one_request_and_a_failure():
    with fake_server(429, b'{"__type": "ThrottlingException", "message": "slow down"}',
                     {"Content-Type": "application/x-amz-json-1.1", "x-amzn-RequestId": "r9"}) as (url, received):
        out = infer_icd10_cm(client_for(url), "text")
    assert len(received) == 1
    assert not out.ok
    assert out.error_type == "ClientError" and out.error_code == "ThrottlingException"
    assert out.http_status == 429 and out.request_id == "r9"
    assert out.raw_body is not None and b"ThrottlingException" in out.raw_body


def test_transport_error_is_classified_by_class_name():
    client = build_client("comprehendmedical", "us-east-1", endpoint_url="http://127.0.0.1:1", credentials=CREDS,
                          connect_timeout=2)
    out = infer_icd10_cm(client, "text")
    assert not out.ok and out.response is None
    assert out.error_code == out.error_type == "EndpointConnectionError"


@pytest.mark.parametrize("text", ["", "x" * 10_001])
def test_local_refusal_makes_no_request(text):
    with fake_server(200, BODY) as (url, received):
        with pytest.raises(ValueError):
            infer_icd10_cm(client_for(url), text)
    assert received == []


def test_boundary_length_is_accepted():
    with fake_server(200, BODY) as (url, received):
        out = infer_icd10_cm(client_for(url), "x" * 10_000)
    assert out.ok and len(received) == 1


def test_stubber_parsing_path_has_no_raw_body():
    from botocore.stub import Stubber

    client = client_for("http://127.0.0.1:9")
    with Stubber(client) as stub:
        stub.add_response("infer_icd10_cm", {"Entities": [], "ModelVersion": "v1"}, {"Text": "abc"})
        out = infer_icd10_cm(client, "abc")
    assert out.ok and out.raw_body is None and out.model_version == "v1"
    assert out.response["Entities"] == []
