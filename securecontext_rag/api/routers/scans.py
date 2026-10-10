"""
Scans router (report section 4.2.4: routing scan requests to the Python
AI core). POST /scans kicks off the pipeline as a background task so the
request returns immediately with a scan_run_id the client can poll.
"""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from api.auth import require_api_key
from api.config import settings
from api.db.models import ScanRunORM
from api.db.session import get_db
from api.schemas.api_schemas import ScanRequest, ScanRunDetail, ScanRunSummary
from api.services.scan_service import run_scan_and_persist

router = APIRouter(prefix="/scans", tags=["scans"])


@router.post("", response_model=ScanRunSummary, dependencies=[Depends(require_api_key)])
def create_scan(
    request: ScanRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> ScanRunORM:
    scan_run = ScanRunORM(RepoName=request.repo_name, PRNumber=request.pr_number, Status="pending")
    db.add(scan_run)
    db.commit()
    db.refresh(scan_run)

    background_tasks.add_task(
        run_scan_and_persist,
        scan_run_id=scan_run.Id,
        repo_path=request.repo_path,
        semgrep_config=request.semgrep_config or settings.semgrep_config,
    )
    return scan_run


@router.get("", response_model=list[ScanRunSummary])
def list_scans(db: Session = Depends(get_db)) -> list[ScanRunORM]:
    return db.query(ScanRunORM).order_by(ScanRunORM.TriggeredAt.desc()).all()


@router.get("/{scan_run_id}", response_model=ScanRunDetail)
def get_scan(scan_run_id: str, db: Session = Depends(get_db)) -> ScanRunORM:
    scan_run = db.get(ScanRunORM, scan_run_id)
    if scan_run is None:
        raise HTTPException(status_code=404, detail="Scan run not found")
    return scan_run
