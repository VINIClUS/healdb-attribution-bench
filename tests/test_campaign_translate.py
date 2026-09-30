import hashlib
import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from habench.campaign.aws import build_client
from habench.campaign.translate import converse_translate

CREDS = ("AKIA" + "X" * 16, "dummy")
MODEL = "us.example.model-v1:0"

BODY = json.dumps({
    "output": {"message": {"role": "assistant", "content": [{"text": "A"}, {"text": "B"}]}},
    "stopReason": "end_turn",
    "usage": {"inputTokens": 12, "outputTokens": 2, "totalTokens": 14},
    "metrics": {"latencyMs": 345},
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
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", received
    finally:
        server.shutdown()
        server.server_close()


def client_for(url: str):
    return build_client("bedrock-runtime", "us-east-1", endpoint_url=url, credentials=CREDS)


HEADERS = {"Content-Type": "application/json", "x-amzn-RequestId": "req-7", "Date": "Wed, 30 Sep 2026 12:00:01 GMT"}


def test_success_request_shape_and_parsing():
    prompt = "  Translate this. \n"
    with fake_server(200, BODY, HEADERS) as (url, received):
        out = converse_translate(client_for(url), model_id=MODEL, prompt=prompt, max_tokens=512, temperature=0.0)
    assert len(received) == 1
    path, _, data = received[0]
    assert path.endswith("/converse") and path.startswith("/model/")
    assert json.loads(data) == {"messages": [{"role": "user", "content": [{"text": prompt}]}],
                                "inferenceConfig": {"maxTokens": 512, "temperature": 0.0}}
    assert out.ok and out.raw_body == BODY
    assert out.output_text == "AB"
    assert out.stop_reason == "end_turn"
    assert (out.input_tokens, out.output_tokens, out.service_latency_ms) == (12, 2, 345)
    assert out.request_id == "req-7" and out.http_date == "Wed, 30 Sep 2026 12:00:01 GMT"
    assert out.http_status == 200
    assert out.response["ResponseMetadata"]["RequestId"] == "req-7"
    assert out.prompt_sha256 == hashlib.sha256(prompt.encode()).hexdigest()
    assert out.temperature == 0.0 and out.max_tokens == 512 and out.model_id == MODEL


def test_temperature_omitted_when_none():
    with fake_server(200, BODY, HEADERS) as (url, received):
        converse_translate(client_for(url), model_id=MODEL, prompt="p", max_tokens=100, temperature=None)
    assert json.loads(received[0][2])["inferenceConfig"] == {"maxTokens": 100}


def test_http_500_single_request_failure():
    with fake_server(500, b'{"message": "boom"}', {"Content-Type": "application/json",
                                                     "x-amzn-ErrorType": "InternalServerException"}) as (url, rec):
        out = converse_translate(client_for(url), model_id=MODEL, prompt="p", max_tokens=10, temperature=0.0)
    assert len(rec) == 1
    assert not out.ok and out.output_text is None and out.response is None
    assert out.error_code == "InternalServerException" and out.http_status == 500


def test_throttling_429_single_request_failure():
    with fake_server(429, b'{"message": "Too many requests"}',
                     {"Content-Type": "application/json", "x-amzn-ErrorType": "ThrottlingException"}) as (url, rec):
        out = converse_translate(client_for(url), model_id=MODEL, prompt="p", max_tokens=10, temperature=0.0)
    assert len(rec) == 1
    assert not out.ok and out.error_code == "ThrottlingException" and out.http_status == 429


def test_stubber_path():
    from botocore.stub import Stubber

    client = client_for("http://127.0.0.1:9")
    resp = {"output": {"message": {"role": "assistant", "content": [{"text": "x"}, {"text": "y"}]}},
            "stopReason": "max_tokens", "usage": {"inputTokens": 1, "outputTokens": 2, "totalTokens": 3},
            "metrics": {"latencyMs": 5}}
    with Stubber(client) as stub:
        stub.add_response("converse", resp)
        out = converse_translate(client, model_id=MODEL, prompt="p", max_tokens=10, temperature=None)
    assert out.ok and out.raw_body is None and out.output_text == "xy" and out.stop_reason == "max_tokens"


@pytest.mark.parametrize("code", ["ThrottlingException", "ModelTimeoutException"])
def test_stubber_client_error(code):
    from botocore.stub import Stubber

    client = client_for("http://127.0.0.1:9")
    with Stubber(client) as stub:
        stub.add_client_error("converse", service_error_code=code, http_status_code=429)
        out = converse_translate(client, model_id=MODEL, prompt="p", max_tokens=10, temperature=0.0)
    assert not out.ok and out.error_code == code and out.output_text is None
