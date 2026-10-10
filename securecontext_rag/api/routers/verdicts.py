"""
Verdicts router: reviewer feedback capture (report section 4.2.4/4.2.5 --
"supports reviewer feedback capture, and stores that feedback for future
calibration refinement, closing the loop between detection and developer
action"). This is the feedback-loop entry point Figure 3.1 shows flowing
back into the calibration subsystem.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.auth import require_api_key
from api.db.models import ReviewerDecisionORM, VerdictORM
from api.db.session import get_db
from api.schemas.api_schemas import ReviewRequest, ReviewerDecisionOut, VerdictOut

router = APIRouter(prefix="/verdicts", tags=["verdicts"])


@router.get("/{verdict_id}", response_model=VerdictOut)
def get_verdict(verdict_id: str, db: Session = Depends(get_db)) -> VerdictORM:
    verdict = db.get(VerdictORM, verdict_id)
    if verdict is None:
        raise HTTPException(status_code=404, detail="Verdict not found")
    return verdict


@router.post("/{verdict_id}/review", response_model=ReviewerDecisionOut, dependencies=[Depends(require_api_key)])
def submit_review(verdict_id: str, request: ReviewRequest, db: Session = Depends(get_db)) -> ReviewerDecisionORM:
    verdict = db.get(VerdictORM, verdict_id)
    if verdict is None:
        raise HTTPException(status_code=404, detail="Verdict not found")

    decision = ReviewerDecisionORM(
        VerdictId=verdict_id,
        ReviewerId=request.reviewer_id,
        Decision=request.decision,
        Note=request.note,
    )
    db.add(decision)
    db.commit()
    db.refresh(decision)
    return decision


@router.get("/{verdict_id}/reviews", response_model=list[ReviewerDecisionOut])
def list_reviews(verdict_id: str, db: Session = Depends(get_db)) -> list[ReviewerDecisionORM]:
    return (
        db.query(ReviewerDecisionORM)
        .filter(ReviewerDecisionORM.VerdictId == verdict_id)
        .order_by(ReviewerDecisionORM.DecidedAt.desc())
        .all()
    )
