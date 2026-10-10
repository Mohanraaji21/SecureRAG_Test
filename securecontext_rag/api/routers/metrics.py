"""
Calibration metrics router (report Figure 5.2 / section 3.2.1): exposes
ECE and reliability-diagram data computed from stored verdicts against
reviewer feedback as ground truth. A verdict is treated as "correct" if a
reviewer 'confirmed' it, "incorrect" if 'overruled'; 'unsure' decisions
and unreviewed verdicts are excluded, since ECE requires a ground-truth
correctness label.
"""

from __future__ import annotations

import numpy as np
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from api.db.models import ReviewerDecisionORM, VerdictORM
from api.db.session import get_db
from api.schemas.api_schemas import CalibrationMetricsOut
from core.calibration.metrics import expected_calibration_error, reliability_diagram_data

router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.get("/calibration", response_model=CalibrationMetricsOut)
def calibration_metrics(
    scan_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> CalibrationMetricsOut:
    q = (
        db.query(VerdictORM, ReviewerDecisionORM)
        .join(ReviewerDecisionORM, ReviewerDecisionORM.VerdictId == VerdictORM.Id)
        .filter(ReviewerDecisionORM.Decision.in_(["confirmed", "overruled"]))
    )
    if scan_id:
        from api.db.models import FindingORM

        q = q.join(FindingORM, FindingORM.Id == VerdictORM.FindingId).filter(
            FindingORM.ScanRunId == scan_id
        )

    rows = q.all()

    confidences, correct = [], []
    for verdict, decision in rows:
        if verdict.CalibratedConfidence is None:
            continue
        confidences.append(verdict.CalibratedConfidence)
        correct.append(1.0 if decision.Decision == "confirmed" else 0.0)

    if not confidences:
        return CalibrationMetricsOut(
            n_reviewed_verdicts=0, expected_calibration_error=None, reliability_diagram=None
        )

    conf_arr = np.array(confidences)
    correct_arr = np.array(correct)

    return CalibrationMetricsOut(
        n_reviewed_verdicts=len(confidences),
        expected_calibration_error=round(
            expected_calibration_error(conf_arr, correct_arr), 4
        ),
        reliability_diagram=reliability_diagram_data(conf_arr, correct_arr),
    )
