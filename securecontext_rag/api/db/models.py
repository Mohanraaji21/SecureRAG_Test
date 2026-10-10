"""
Persistence models -- matches Appendix A.3's planned database schema
exactly (table names, key columns), with the operationally-necessary
extra columns noted inline. This is the "Persistence Layer" subsystem
from Table 4.5, now implemented in SQLAlchemy against SQL Server instead
of EF Core.

Appendix A.3 target:
  ScanRuns:          Id, RepoName, PRNumber, TriggeredAt
  Findings:          Id, ScanRunId, CweId, FilePath, Line, RawVerdict
  Verdicts:          Id, FindingId, CalibratedConfidence, Justification, CitedEvidenceJson
  ReviewerDecisions: Id, VerdictId, ReviewerId, Decision, DecidedAt
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ScanRunORM(Base):
    __tablename__ = "ScanRuns"

    Id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    RepoName: Mapped[str] = mapped_column(String(500))
    PRNumber: Mapped[int | None] = mapped_column(Integer, nullable=True)
    TriggeredAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    # Operational additions beyond Appendix A.3 (needed to run scans as a
    # background task and expose progress to the dashboard):
    Status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|running|completed|failed
    ErrorMessage: Mapped[str | None] = mapped_column(Text, nullable=True)
    CompletedAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    findings: Mapped[list["FindingORM"]] = relationship(back_populates="scan_run", cascade="all, delete-orphan")


class FindingORM(Base):
    __tablename__ = "Findings"

    Id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    ScanRunId: Mapped[str] = mapped_column(String(36), ForeignKey("ScanRuns.Id"))
    CweId: Mapped[str | None] = mapped_column(String(20), nullable=True)
    FilePath: Mapped[str] = mapped_column(String(1000))
    Line: Mapped[int] = mapped_column(Integer)
    RawVerdict: Mapped[str | None] = mapped_column(String(20), nullable=True)  # populated once adjudicated

    # Operational additions (raw Semgrep fields needed to reconstruct the
    # finding for display / re-adjudication):
    RuleId: Mapped[str] = mapped_column(String(300))
    EndLine: Mapped[int | None] = mapped_column(Integer, nullable=True)
    Severity: Mapped[str] = mapped_column(String(20), default="warning")
    Message: Mapped[str] = mapped_column(Text)
    CodeSnippet: Mapped[str] = mapped_column(Text)

    scan_run: Mapped["ScanRunORM"] = relationship(back_populates="findings")
    verdict: Mapped["VerdictORM | None"] = relationship(back_populates="finding", uselist=False, cascade="all, delete-orphan")


class VerdictORM(Base):
    __tablename__ = "Verdicts"

    Id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    FindingId: Mapped[str] = mapped_column(String(36), ForeignKey("Findings.Id"), unique=True)
    CalibratedConfidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    Justification: Mapped[str] = mapped_column(Text)
    CitedEvidenceJson: Mapped[str] = mapped_column(Text, default="[]")  # JSON-encoded list[CitedEvidence]

    # Operational additions:
    Verdict: Mapped[str] = mapped_column(String(20))  # true_positive|false_positive|needs_review
    RawConfidence: Mapped[float] = mapped_column(Float)
    ModelUsed: Mapped[str | None] = mapped_column(String(200), nullable=True)
    FailOpen: Mapped[bool] = mapped_column(default=False)
    CreatedAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    finding: Mapped["FindingORM"] = relationship(back_populates="verdict")
    reviewer_decisions: Mapped[list["ReviewerDecisionORM"]] = relationship(
        back_populates="verdict", cascade="all, delete-orphan"
    )


class ReviewerDecisionORM(Base):
    __tablename__ = "ReviewerDecisions"

    Id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    VerdictId: Mapped[str] = mapped_column(String(36), ForeignKey("Verdicts.Id"))
    ReviewerId: Mapped[str] = mapped_column(String(200))
    Decision: Mapped[str] = mapped_column(String(20))  # confirmed|overruled|unsure
    DecidedAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    # Operational addition: free-text note from the reviewer, useful for
    # future calibration refinement (section 4.2.5's feedback loop).
    Note: Mapped[str | None] = mapped_column(Text, nullable=True)

    verdict: Mapped["VerdictORM"] = relationship(back_populates="reviewer_decisions")
