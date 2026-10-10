"""
Data contracts for SecureContext-RAG.

These models are the "documented, versioned JSON schema" referenced in
report section 4.6 as the interface contract between the Python AI core
(Tier 1) and the application layer (Tier 2). Phase 2's FastAPI layer will
serialize/deserialize these same models directly, so this file is the
single source of truth for the contract -- do not duplicate it.

`Verdict` mirrors Appendix A.2's planned structured output schema exactly,
with `reviewer_decision` populated later by Tier 2 once a human reviews it.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel, Field


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return str(uuid4())


class VerdictLabel(str, Enum):
    """The three-way verdict per Appendix A.2 ('needs_review' is the
    fail-open / low-confidence / malformed-output outcome per section 4.6)."""

    TRUE_POSITIVE = "true_positive"
    FALSE_POSITIVE = "false_positive"
    NEEDS_REVIEW = "needs_review"


class ReviewerDecision(str, Enum):
    CONFIRMED = "confirmed"
    OVERRULED = "overruled"
    UNSURE = "unsure"


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


# ---------------------------------------------------------------------------
# 4.2.1 Static Analysis and Candidate Generation
# ---------------------------------------------------------------------------
class Finding(BaseModel):
    """One raw Semgrep candidate finding, prior to any LLM adjudication."""

    finding_id: str = Field(default_factory=_new_id)
    rule_id: str
    cwe_id: Optional[str] = None
    file_path: str
    line: int
    end_line: Optional[int] = None
    severity: Severity = Severity.WARNING
    message: str
    code_snippet: str


# ---------------------------------------------------------------------------
# 4.2.2 Retrieval-Augmented Knowledge Subsystem
# ---------------------------------------------------------------------------
class KnowledgeItem(BaseModel):
    """A single knowledge-level (not code-level, per section 4.6) entry in
    the FAISS-backed knowledge base: either a CWE definition or a historical
    vulnerability-fix pair."""

    item_id: str = Field(default_factory=_new_id)
    cwe_id: str
    kind: str  # "cwe_definition" | "vuln_fix_pair"
    title: str
    text: str  # the content that gets embedded and retrieved


class RetrievedEvidence(BaseModel):
    """One retrieval hit surfaced to the LLM and, per section 3.2.2, cited
    back to the developer as a trust signal."""

    source: str  # e.g. "CWE-89 definition"
    knowledge_item_id: str
    similarity_score: float


# ---------------------------------------------------------------------------
# 4.2.3 LLM Adjudication and Confidence Calibration -- Appendix A.2 schema
# ---------------------------------------------------------------------------
class CitedEvidence(BaseModel):
    source: str
    id: str


class Verdict(BaseModel):
    """Matches Appendix A.2's planned structured output schema."""

    finding_id: str
    cwe_id: Optional[str] = None
    verdict: VerdictLabel
    raw_confidence: float = Field(ge=0.0, le=1.0)
    calibrated_confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    justification: str
    cited_evidence: list[CitedEvidence] = Field(default_factory=list)
    reviewer_decision: Optional[ReviewerDecision] = None

    # Bookkeeping not in the original appendix draft but needed operationally
    model_used: Optional[str] = None
    fail_open: bool = False  # True if this verdict is a fail-open fallback
    created_at: datetime = Field(default_factory=_now)


# ---------------------------------------------------------------------------
# 4.2.4 / Appendix A.3 -- scan-run level container
# ---------------------------------------------------------------------------
class ScanRun(BaseModel):
    scan_run_id: str = Field(default_factory=_new_id)
    repo_name: str
    pr_number: Optional[int] = None
    triggered_at: datetime = Field(default_factory=_now)
    findings: list[Finding] = Field(default_factory=list)
    verdicts: list[Verdict] = Field(default_factory=list)
