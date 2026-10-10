"""
Tests for the GitHub webhook: signature verification and the full
checkout -> scan flow, with git itself mocked (no real network clone).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import tempfile

import pytest

# Reuse the same throwaway-DB bootstrapping pattern as test_api.py
_tmp_db_fd, _tmp_db_path = tempfile.mkstemp(suffix=".db")
os.close(_tmp_db_fd)
os.environ.setdefault("SCR_DATABASE_URL", f"sqlite:///{_tmp_db_path}")
os.environ.setdefault("SCR_API_KEY", "test-key")
os.environ.setdefault("SCR_GITHUB_WEBHOOK_SECRET", "test-webhook-secret")

from fastapi.testclient import TestClient  # noqa: E402

from api.config import settings  # noqa: E402
from api.db.session import init_db  # noqa: E402
from api.main import app  # noqa: E402
import api.services.scan_service as scan_service  # noqa: E402
from core.schemas.models import Finding, Verdict, VerdictLabel  # noqa: E402

SECRET = "test-webhook-secret"
# The settings singleton may already have been constructed by another test
# module (e.g. test_api.py) before this module's env vars were set -- force
# it here so signature verification uses the same secret this file signs
# with, regardless of test collection order.
settings.github_webhook_secret = SECRET


@pytest.fixture(scope="module", autouse=True)
def _setup_db():
    init_db()
    yield


def _sign(body: bytes) -> str:
    mac = hmac.new(SECRET.encode(), body, hashlib.sha256)
    return f"sha256={mac.hexdigest()}"


@pytest.fixture
def client(monkeypatch, tmp_path):
    class FakePipeline:
        def run_on_findings(self, findings):
            return [
                Verdict(
                    finding_id=f.finding_id,
                    cwe_id=f.cwe_id,
                    verdict=VerdictLabel.TRUE_POSITIVE,
                    raw_confidence=0.8,
                    calibrated_confidence=0.8,
                    justification="stub",
                )
                for f in findings
            ]

    def fake_run_semgrep(target_path, config="auto"):
        return [
            Finding(
                rule_id="r1", cwe_id="CWE-89", file_path="a.py", line=1,
                message="m", code_snippet="x",
            )
        ]

    def fake_ensure_pr_checkout(repo_full_name, pr_number, clone_url, head_sha=None, checkouts_root=None):
        # Stand in for a real git clone -- just hand back a real, empty dir.
        d = tmp_path / "checkout"
        d.mkdir(exist_ok=True)
        return d

    monkeypatch.setattr(scan_service, "get_pipeline", lambda: FakePipeline())
    monkeypatch.setattr(scan_service, "run_semgrep", fake_run_semgrep)

    import api.services.git_checkout as git_checkout_module
    monkeypatch.setattr(git_checkout_module, "ensure_pr_checkout", fake_ensure_pr_checkout)
    # scan_service imports ensure_pr_checkout lazily inside the function,
    # so patching the module-level name above is sufficient.

    return TestClient(app)


def _pr_payload(action="opened", number=42):
    return {
        "action": action,
        "number": number,
        "repository": {"full_name": "acme-org/webapp", "clone_url": "https://github.com/acme-org/webapp.git"},
        "pull_request": {
            "head": {
                "sha": "abc123deadbeef",
                "repo": {"clone_url": "https://github.com/acme-org/webapp.git"},
            }
        },
    }


def test_webhook_rejects_missing_signature(client):
    body = json.dumps(_pr_payload()).encode()
    resp = client.post(
        "/webhooks/github",
        content=body,
        headers={"Content-Type": "application/json", "X-GitHub-Event": "pull_request"},
    )
    assert resp.status_code == 401


def test_webhook_rejects_invalid_signature(client):
    body = json.dumps(_pr_payload()).encode()
    resp = client.post(
        "/webhooks/github",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-GitHub-Event": "pull_request",
            "X-Hub-Signature-256": "sha256=0000invalid",
        },
    )
    assert resp.status_code == 401


def test_webhook_ignores_non_pull_request_event(client):
    body = json.dumps({"zen": "keep it logically awesome"}).encode()
    resp = client.post(
        "/webhooks/github",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-GitHub-Event": "ping",
            "X-Hub-Signature-256": _sign(body),
        },
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ignored"


def test_webhook_ignores_unhandled_pr_action(client):
    body = json.dumps(_pr_payload(action="closed")).encode()
    resp = client.post(
        "/webhooks/github",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-GitHub-Event": "pull_request",
            "X-Hub-Signature-256": _sign(body),
        },
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ignored"


def test_webhook_triggers_checkout_and_scan(client):
    body = json.dumps(_pr_payload(action="opened", number=99)).encode()
    resp = client.post(
        "/webhooks/github",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-GitHub-Event": "pull_request",
            "X-Hub-Signature-256": _sign(body),
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "scan_triggered"
    scan_run_id = data["scan_run_id"]

    # TestClient runs BackgroundTasks synchronously, so checkout + scan
    # have already completed by the time we check.
    detail = client.get(f"/scans/{scan_run_id}").json()
    assert detail["Status"] == "completed"
    assert detail["PRNumber"] == 99
    assert len(detail["findings"]) == 1
