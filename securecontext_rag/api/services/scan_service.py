"""
Scan service: bridges the Phase 1 AI core (imported directly as a Python
library -- not shelled out to, per the decoupled-but-in-process design
implied by section 4.2.4) to the Phase 2 persistence layer.

`run_scan_and_persist` is what a FastAPI BackgroundTask calls: it runs the
full Semgrep -> retrieval -> adjudication -> calibration pipeline and
writes every Finding + Verdict row, updating ScanRun.Status as it goes.
Any failure updates the run's Status to 'failed' with an ErrorMessage
rather than leaving it stuck 'running' forever.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache

from sqlalchemy.orm import Session

from api.config import settings
from api.db.models import FindingORM, ScanRunORM, VerdictORM
from core.adjudication.ollama_client import OllamaClient
from core.calibration.temperature_scaling import TemperatureScaler
from core.pipeline import TriagePipeline
from core.retrieval.faiss_index import KnowledgeIndex, SentenceTransformerEmbedder
from core.retrieval.kb_builder import load_from_json
from core.sast.semgrep_runner import run_semgrep

logger = logging.getLogger("securecontext_rag.api.scan_service")


@lru_cache(maxsize=1)
def get_pipeline() -> TriagePipeline:
    """Builds the TriagePipeline once per process and caches it -- the
    embedding model and FAISS index are expensive to construct, so this
    avoids rebuilding them on every request. Cleared automatically if the
    process restarts; there is no hot-reload of the knowledge base yet
    (see README_PHASE2.md for the documented limitation)."""
    items = load_from_json()
    embedder = SentenceTransformerEmbedder(model_name=settings.embedding_model)
    index = KnowledgeIndex.build(items, embedder)
    llm_client = OllamaClient(base_url=settings.ollama_url, model=settings.ollama_model)
    return TriagePipeline(
        knowledge_index=index,
        llm_client=llm_client,
        calibrator=TemperatureScaler(),
        top_k_evidence=settings.top_k_evidence,
    )


def run_scan_and_persist(scan_run_id: str, repo_path: str, semgrep_config: str) -> None:
    """Runs the AI core pipeline and persists results. Designed to be
    called from a FastAPI BackgroundTask, so it opens its own DB session
    rather than reusing the request's (which closes when the response is
    sent)."""
    from api.db.session import SessionLocal

    db: Session = SessionLocal()
    try:
        scan_run = db.get(ScanRunORM, scan_run_id)
        if scan_run is None:
            logger.error("ScanRun %s not found when starting background scan", scan_run_id)
            return

        scan_run.Status = "running"
        db.commit()

        pipeline = get_pipeline()
        findings = run_semgrep(repo_path, config=semgrep_config)
        verdicts = pipeline.run_on_findings(findings)
        verdict_by_finding_id = {v.finding_id: v for v in verdicts}

        for finding in findings:
            finding_orm = FindingORM(
                ScanRunId=scan_run.Id,
                CweId=finding.cwe_id,
                FilePath=finding.file_path,
                Line=finding.line,
                EndLine=finding.end_line,
                RuleId=finding.rule_id,
                Severity=finding.severity.value,
                Message=finding.message,
                CodeSnippet=finding.code_snippet,
            )
            verdict = verdict_by_finding_id.get(finding.finding_id)
            if verdict is not None:
                finding_orm.RawVerdict = verdict.verdict.value
            db.add(finding_orm)
            db.flush()  # populate finding_orm.Id before creating the Verdict row

            if verdict is not None:
                verdict_orm = VerdictORM(
                    FindingId=finding_orm.Id,
                    Verdict=verdict.verdict.value,
                    RawConfidence=verdict.raw_confidence,
                    CalibratedConfidence=verdict.calibrated_confidence,
                    Justification=verdict.justification,
                    CitedEvidenceJson=json.dumps([e.model_dump() for e in verdict.cited_evidence]),
                    ModelUsed=verdict.model_used,
                    FailOpen=verdict.fail_open,
                )
                db.add(verdict_orm)

        scan_run.Status = "completed"
        from datetime import datetime, timezone

        scan_run.CompletedAt = datetime.now(timezone.utc)
        db.commit()

    except Exception as exc:  # noqa: BLE001 - top-level background task guard
        logger.exception("Scan run %s failed", scan_run_id)
        db.rollback()
        scan_run = db.get(ScanRunORM, scan_run_id)
        if scan_run is not None:
            scan_run.Status = "failed"
            scan_run.ErrorMessage = str(exc)[:2000]
            db.commit()
    finally:
        db.close()


def checkout_and_run_scan_and_persist(
    scan_run_id: str,
    repo_full_name: str,
    pr_number: int,
    clone_url: str,
    head_sha: str | None,
    semgrep_config: str,
) -> None:
    """Webhook entry point (report §4.2.5): clones/updates the PR's head
    commit first, then delegates to run_scan_and_persist with the real
    local path. Checkout failures are routed into the same
    ScanRun.Status='failed' handling as any other pipeline error, rather
    than being a separate unhandled failure mode -- the webhook and the
    manual `POST /scans` path end up equally robust."""
    from api.db.session import SessionLocal
    from api.services.git_checkout import GitCheckoutError, ensure_pr_checkout

    db: Session = SessionLocal()
    try:
        scan_run = db.get(ScanRunORM, scan_run_id)
        if scan_run is None:
            logger.error("ScanRun %s not found when starting webhook checkout", scan_run_id)
            return

        scan_run.Status = "running"
        db.commit()

        repo_path = ensure_pr_checkout(
            repo_full_name=repo_full_name,
            pr_number=pr_number,
            clone_url=clone_url,
            head_sha=head_sha,
        )
    except GitCheckoutError as exc:
        logger.exception("Checkout failed for scan run %s", scan_run_id)
        db.rollback()
        scan_run = db.get(ScanRunORM, scan_run_id)
        if scan_run is not None:
            scan_run.Status = "failed"
            scan_run.ErrorMessage = f"Git checkout failed: {exc}"[:2000]
            db.commit()
        return
    finally:
        db.close()

    # Checkout succeeded -- hand off to the same code path POST /scans uses,
    # with its own fresh session (consistent with run_scan_and_persist's
    # own session-per-background-task pattern).
    run_scan_and_persist(scan_run_id=scan_run_id, repo_path=str(repo_path), semgrep_config=semgrep_config)
