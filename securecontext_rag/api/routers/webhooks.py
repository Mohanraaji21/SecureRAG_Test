"""
GitHub webhook receiver (report section 4.2.5, scoped as a stretch goal
per section 1.4 / Table 5.6 -- "manual scan trigger is the fallback core
deliverable"). Validates the HMAC-SHA256 signature GitHub sends, and on a
pull_request event (opened/synchronize/reopened) clones the PR's head
commit (api/services/git_checkout.py) and triggers a scan against it --
fully automatic, no manual checkout step required.

See docs/GITHUB_WEBHOOK_SETUP.md for how to point a real GitHub repo's
webhook at this endpoint.
"""

from __future__ import annotations

import hashlib
import hmac

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from api.config import settings
from api.db.models import ScanRunORM
from api.db.session import get_db
from api.services.scan_service import checkout_and_run_scan_and_persist

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def _verify_signature(payload: bytes, signature_header: str | None) -> None:
    if not signature_header or not signature_header.startswith("sha256="):
        raise HTTPException(status_code=401, detail="Missing or malformed X-Hub-Signature-256")

    expected = hmac.new(
        settings.github_webhook_secret.encode(), payload, hashlib.sha256
    ).hexdigest()
    provided = signature_header.removeprefix("sha256=")
    if not hmac.compare_digest(expected, provided):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")


@router.post("/github")
async def github_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_hub_signature_256: str | None = Header(default=None),
    x_github_event: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> dict:
    raw_body = await request.body()
    _verify_signature(raw_body, x_hub_signature_256)

    if x_github_event != "pull_request":
        return {"status": "ignored", "reason": f"event type '{x_github_event}' is not handled"}

    payload = await request.json()
    action = payload.get("action")
    if action not in ("opened", "synchronize", "reopened"):
        return {"status": "ignored", "reason": f"pull_request action '{action}' is not handled"}

    pr = payload.get("pull_request", {})
    repo_name = payload.get("repository", {}).get("full_name", "unknown/unknown")
    pr_number = payload.get("number")
    clone_url = pr.get("head", {}).get("repo", {}).get("clone_url") or payload.get(
        "repository", {}
    ).get("clone_url")
    head_sha = pr.get("head", {}).get("sha")

    if not clone_url or pr_number is None:
        raise HTTPException(status_code=422, detail="Payload missing repository clone_url or PR number")

    scan_run = ScanRunORM(RepoName=repo_name, PRNumber=pr_number, Status="pending")
    db.add(scan_run)
    db.commit()
    db.refresh(scan_run)

    background_tasks.add_task(
        checkout_and_run_scan_and_persist,
        scan_run_id=scan_run.Id,
        repo_full_name=repo_name,
        pr_number=pr_number,
        clone_url=clone_url,
        head_sha=head_sha,
        semgrep_config=settings.semgrep_config,
    )

    return {"status": "scan_triggered", "scan_run_id": scan_run.Id}
