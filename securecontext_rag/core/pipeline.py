"""
Pipeline orchestrator (report section 4.3 / 4.6).

Wires together Semgrep -> retrieval -> LLM adjudication -> calibration
into the end-to-end per-finding flow described in report Figure 3.1.

Design principles enforced here (section 4.6):
  - Per-finding, not monolithic, processing: each finding is adjudicated
    independently, so one bad LLM call can't take down the whole scan.
  - Fail-open safety: handled inside OllamaClient.adjudicate(); this
    module never suppresses a finding on error.
  - Knowledge-level, CWE-specific retrieval: delegated to KnowledgeIndex.
"""

from __future__ import annotations

import logging
from pathlib import Path

from core.adjudication.ollama_client import OllamaClient
from core.calibration.temperature_scaling import TemperatureScaler
from core.retrieval.faiss_index import KnowledgeIndex
from core.sast.semgrep_runner import run_semgrep
from core.schemas.models import Finding, ScanRun, Verdict

logger = logging.getLogger("securecontext_rag.pipeline")


class TriagePipeline:
    def __init__(
        self,
        knowledge_index: KnowledgeIndex,
        llm_client: OllamaClient,
        calibrator: TemperatureScaler | None = None,
        top_k_evidence: int = 3,
    ):
        self.knowledge_index = knowledge_index
        self.llm_client = llm_client
        self.calibrator = calibrator or TemperatureScaler()  # identity if unfitted
        self.top_k_evidence = top_k_evidence

    def process_finding(self, finding: Finding) -> Verdict:
        """The single-finding unit of work (section 4.6's "per-finding, not
        monolithic, processing"). Never raises: adjudicate() is fail-open,
        and any unexpected error here is itself converted to a
        needs_review verdict so a bug in orchestration can't silently
        drop a real finding."""
        try:
            evidence = self.knowledge_index.query(finding, top_k=self.top_k_evidence)
            evidence_texts = {
                e.knowledge_item_id: (self.knowledge_index.get_item_text(e.knowledge_item_id) or "")
                for e in evidence
            }
            verdict = self.llm_client.adjudicate(finding, evidence, evidence_texts)
            verdict.calibrated_confidence = self.calibrator.calibrate(verdict.raw_confidence)
            return verdict
        except Exception:  # noqa: BLE001 - last-resort fail-open guard
            logger.exception("Unexpected error processing finding %s", finding.finding_id)
            from core.schemas.models import VerdictLabel

            return Verdict(
                finding_id=finding.finding_id,
                cwe_id=finding.cwe_id,
                verdict=VerdictLabel.NEEDS_REVIEW,
                raw_confidence=0.0,
                calibrated_confidence=0.0,
                justification="Fail-open fallback: unexpected pipeline error. Routed to manual review.",
                fail_open=True,
            )

    def run_on_findings(self, findings: list[Finding]) -> list[Verdict]:
        return [self.process_finding(f) for f in findings]

    def run_on_repo(
        self,
        repo_path: str | Path,
        repo_name: str,
        pr_number: int | None = None,
        semgrep_config: str = "auto",
    ) -> ScanRun:
        """End-to-end: Semgrep scan -> per-finding adjudication -> ScanRun."""
        findings = run_semgrep(repo_path, config=semgrep_config)
        verdicts = self.run_on_findings(findings)
        return ScanRun(
            repo_name=repo_name,
            pr_number=pr_number,
            findings=findings,
            verdicts=verdicts,
        )
