"""
API-level tests. Uses a fresh temp SQLite DB per test session (never the
dev DB) and monkeypatches api.services.scan_service.get_pipeline so no
real Semgrep/Ollama/sentence-transformers calls happen.
"""

from __future__ import annotations

import os
import tempfile

import pytest
from fastapi.testclient import TestClient

# --- Point settings at a throwaway SQLite DB before importing the app ----
_tmp_db_fd, _tmp_db_path = tempfile.mkstemp(suffix=".db")
os.close(_tmp_db_fd)
os.environ["SCR_DATABASE_URL"] = f"sqlite:///{_tmp_db_path}"
os.environ["SCR_API_KEY"] = "test-key"

from api.db.models import FindingORM, ScanRunORM, VerdictORM  # noqa: E402
from api.db.session import SessionLocal, init_db  # noqa: E402
from api.main import app  # noqa: E402
import api.services.scan_service as scan_service  # noqa: E402
from core.schemas.models import Finding, Verdict, VerdictLabel  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _setup_db():
    init_db()
    yield
    os.remove(_tmp_db_path)


@pytest.fixture
def client(monkeypatch):
    class FakePipeline:
        def run_on_findings(self, findings):
            return [
                Verdict(
                    finding_id=f.finding_id,
                    cwe_id=f.cwe_id,
                    verdict=VerdictLabel.TRUE_POSITIVE,
                    raw_confidence=0.9,
                    calibrated_confidence=0.85,
                    justification="stub",
                    model_used="fake-model",
                )
                for f in findings
            ]

    def fake_run_semgrep(target_path, config="auto"):
        return [
            Finding(
                rule_id="test-rule",
                cwe_id="CWE-89",
                file_path="app.py",
                line=1,
                message="stub finding",
                code_snippet="x = 1",
            )
        ]

    monkeypatch.setattr(scan_service, "get_pipeline", lambda: FakePipeline())
    monkeypatch.setattr(scan_service, "run_semgrep", fake_run_semgrep)

    return TestClient(app)


AUTH_HEADERS = {"X-API-Key": "test-key"}


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_create_scan_requires_api_key(client):
    resp = client.post("/scans", json={"repo_path": ".", "repo_name": "org/repo"})
    assert resp.status_code == 422 or resp.status_code == 401  # missing header


def test_full_scan_flow(client):
    create_resp = client.post(
        "/scans",
        json={"repo_path": ".", "repo_name": "org/repo", "pr_number": 7},
        headers=AUTH_HEADERS,
    )
    assert create_resp.status_code == 200
    scan_run_id = create_resp.json()["Id"]
    assert create_resp.json()["Status"] == "pending"

    # TestClient runs BackgroundTasks synchronously before returning, so
    # the scan is already complete by the time we fetch it.
    detail_resp = client.get(f"/scans/{scan_run_id}")
    assert detail_resp.status_code == 200
    detail = detail_resp.json()
    assert detail["Status"] == "completed"
    assert len(detail["findings"]) == 1
    finding = detail["findings"][0]
    assert finding["verdict"]["Verdict"] == "true_positive"
    assert finding["verdict"]["CalibratedConfidence"] == 0.85

    # Findings listing, confidence-ranked
    findings_resp = client.get("/findings", params={"scan_id": scan_run_id})
    assert findings_resp.status_code == 200
    assert len(findings_resp.json()) == 1

    # Reviewer feedback
    verdict_id = finding["verdict"]["Id"]
    review_resp = client.post(
        f"/verdicts/{verdict_id}/review",
        json={"reviewer_id": "alice", "decision": "confirmed"},
        headers=AUTH_HEADERS,
    )
    assert review_resp.status_code == 200
    assert review_resp.json()["Decision"] == "confirmed"

    # Calibration metrics now has one reviewed verdict
    metrics_resp = client.get("/metrics/calibration", params={"scan_id": scan_run_id})
    assert metrics_resp.status_code == 200
    assert metrics_resp.json()["n_reviewed_verdicts"] == 1


def test_get_nonexistent_scan_404(client):
    resp = client.get("/scans/does-not-exist")
    assert resp.status_code == 404


def test_review_requires_api_key(client):
    resp = client.post(
        "/verdicts/some-id/review",
        json={"reviewer_id": "bob", "decision": "confirmed"},
    )
    assert resp.status_code in (401, 422)


def test_review_invalid_decision_rejected(client):
    create_resp = client.post(
        "/scans", json={"repo_path": ".", "repo_name": "org/repo2"}, headers=AUTH_HEADERS
    )
    scan_run_id = create_resp.json()["Id"]
    detail = client.get(f"/scans/{scan_run_id}").json()
    verdict_id = detail["findings"][0]["verdict"]["Id"]

    resp = client.post(
        f"/verdicts/{verdict_id}/review",
        json={"reviewer_id": "carol", "decision": "not_a_real_decision"},
        headers=AUTH_HEADERS,
    )
    assert resp.status_code == 422
