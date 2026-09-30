import os
import re
import socket
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

SECRET_PATTERNS = {
    "aws_access_key_id": re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    "aws_secret_access_key": re.compile(r"(?i)aws_secret_access_key\s*[:=]\s*\S{20,}"),
    "openai_key": re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}"),
    "anthropic_key": re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}"),
    "private_key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "hardcoded_password": re.compile(r"(?i)\b(?:password|passwd|pwd)\s*=\s*['\"][^'\"\s]{4,}['\"]"),
}
IGNORE_MARK = "secret-scan: ignore"


def _repo_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout
    return [ROOT / p for p in out.splitlines() if p]


def test_no_secrets_in_repo():
    hits = []
    for path in _repo_files():
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            if IGNORE_MARK in line:
                continue
            for name, rx in SECRET_PATTERNS.items():
                if rx.search(line):
                    hits.append(f"{path.relative_to(ROOT)}:{lineno}: {name}")
    assert not hits, "possible secrets:\n" + "\n".join(hits)


def test_cloud_credentials_blanked():
    assert os.environ["AWS_SHARED_CREDENTIALS_FILE"] == os.devnull
    assert os.environ["AWS_CONFIG_FILE"] == os.devnull
    assert "AWS_ACCESS_KEY_ID" not in os.environ
    assert "HAB_PAID_CALLS" not in os.environ


def test_network_blocked_outside_loopback():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        with pytest.raises(RuntimeError, match="network access blocked"):
            s.connect(("192.0.2.1", 443))  # TEST-NET-1, never routable
