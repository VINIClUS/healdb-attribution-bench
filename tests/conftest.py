import ipaddress
import os
import socket

import pytest

_CLOUD_VARS = (
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "AWS_PROFILE",
    "AWS_DEFAULT_PROFILE",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "HAB_PAID_CALLS",
)


def _is_loopback(address) -> bool:
    if not isinstance(address, tuple) or not address:
        return False
    host = address[0]
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


@pytest.fixture(autouse=True)
def _no_cloud_no_network(monkeypatch):
    """Tests never reach AWS or any non-loopback host, whatever the caller's environment."""
    for var in _CLOUD_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", os.devnull)
    monkeypatch.setenv("AWS_CONFIG_FILE", os.devnull)
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")

    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex

    def _check(sock, address):
        if sock.family == getattr(socket, "AF_UNIX", None) or _is_loopback(address):
            return
        raise RuntimeError(f"network access blocked in tests: {address!r}")

    def connect(self, address):
        _check(self, address)
        return real_connect(self, address)

    def connect_ex(self, address):
        _check(self, address)
        return real_connect_ex(self, address)

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)
