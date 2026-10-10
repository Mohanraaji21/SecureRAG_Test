"""
Request/response contracts for the FastAPI layer. Kept separate from
core/schemas/models.py (the AI-core <-> app-layer contract) because these
are DB-row-shaped API views, not the internal pipeline's working types --
though field names deliberately mirror them for consistency.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ScanRequest(BaseModel):
    repo_path: str = Field(..., description="Local filesystem path to the checked-out repo to scan")
    repo_name: str = Field(..., description="e.g. 'my-org/my-repo'")
    pr_number: int | None = None
    semgrep_config: str | None = None  # falls back to settings.semgrep_config


class ScanRunSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    Id: str
    RepoName: str
    PRNumber: int | None
    TriggeredAt: datetime
    Status: str
    ErrorMessage: str | None
    CompletedAt: datetime | None


class CitedEvidenceOut(BaseModel):
    source: str
    id: str


class VerdictOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    Id: str
    FindingId: str
    Verdict: str
    RawConfidence: float
    CalibratedConfidence: float | None
    Justification: str
    ModelUsed: str | None
    FailOpen: bool
    CreatedAt: datetime


class FindingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    Id: str
    ScanRunId: str
    RuleId: str
    CweId: str | None
    FilePath: str
    Line: int
    EndLine: int | None
    Severity: str
    Message: str
    CodeSnippet: str
    verdict: VerdictOut | None = None


class ScanRunDetail(ScanRunSummary):
    findings: list[FindingOut] = Field(default_factory=list)


class ReviewRequest(BaseModel):
    reviewer_id: str
    decision: str = Field(..., pattern="^(confirmed|overruled|unsure)$")
    note: str | None = None


class ReviewerDecisionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    Id: str
    VerdictId: str
    ReviewerId: str
    Decision: str
    DecidedAt: datetime
    Note: str | None


class CalibrationMetricsOut(BaseModel):
    n_reviewed_verdicts: int
    expected_calibration_error: float | None
    reliability_diagram: list[dict] | None
