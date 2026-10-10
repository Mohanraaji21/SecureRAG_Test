"""
Findings router (report section 4.2.5: "confidence-ranked findings").
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload

from api.db.models import FindingORM, VerdictORM
from api.db.session import get_db
from api.schemas.api_schemas import FindingOut

router = APIRouter(prefix="/findings", tags=["findings"])


@router.get("", response_model=list[FindingOut])
def list_findings(
    scan_id: str | None = Query(default=None),
    min_confidence: float | None = Query(default=None, ge=0.0, le=1.0),
    cwe_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[FindingORM]:
    q = db.query(FindingORM).options(joinedload(FindingORM.verdict))
    if scan_id:
        q = q.filter(FindingORM.ScanRunId == scan_id)
    if cwe_id:
        q = q.filter(FindingORM.CweId == cwe_id)

    findings = q.all()

    if min_confidence is not None:
        findings = [
            f for f in findings
            if f.verdict is not None
            and f.verdict.CalibratedConfidence is not None
            and f.verdict.CalibratedConfidence >= min_confidence
        ]

    # Confidence-ranked: highest calibrated confidence first; unadjudicated
    # findings (verdict is None) sort last.
    findings.sort(
        key=lambda f: f.verdict.CalibratedConfidence
        if f.verdict and f.verdict.CalibratedConfidence is not None
        else -1.0,
        reverse=True,
    )
    return findings


@router.get("/{finding_id}", response_model=FindingOut)
def get_finding(finding_id: str, db: Session = Depends(get_db)) -> FindingORM:
    finding = (
        db.query(FindingORM)
        .options(joinedload(FindingORM.verdict))
        .filter(FindingORM.Id == finding_id)
        .first()
    )
    if finding is None:
        raise HTTPException(status_code=404, detail="Finding not found")
    return finding
