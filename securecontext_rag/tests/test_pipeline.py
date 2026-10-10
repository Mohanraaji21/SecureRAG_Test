import numpy as np

from core.calibration.temperature_scaling import TemperatureScaler
from core.pipeline import TriagePipeline
from core.retrieval.faiss_index import KnowledgeIndex
from core.retrieval.kb_builder import load_from_json
from core.schemas.models import Finding, Verdict, VerdictLabel
from eval.run_owasp_benchmark import score_scan_run
from core.schemas.models import ScanRun


class FakeEmbedder:
    def encode(self, texts):
        # Fixed-size deterministic vector; good enough since these tests
        # don't assert on retrieval ranking, only on pipeline wiring.
        return np.array([[1.0, 0.0] for _ in texts], dtype="float32")


class FakeLLMClient:
    """Stands in for OllamaClient -- always returns a confident true_positive
    so pipeline wiring can be tested without a real model."""

    def adjudicate(self, finding, evidence, evidence_texts):
        return Verdict(
            finding_id=finding.finding_id,
            cwe_id=finding.cwe_id,
            verdict=VerdictLabel.TRUE_POSITIVE,
            raw_confidence=0.8,
            justification="stub verdict",
            model_used="fake-model",
        )


def _build_pipeline() -> TriagePipeline:
    items = load_from_json()
    index = KnowledgeIndex.build(items, FakeEmbedder())
    return TriagePipeline(
        knowledge_index=index,
        llm_client=FakeLLMClient(),
        calibrator=TemperatureScaler(),
    )


def test_process_finding_returns_calibrated_verdict():
    pipeline = _build_pipeline()
    finding = Finding(
        rule_id="r1", cwe_id="CWE-89", file_path="a.py", line=1,
        message="sqli", code_snippet="x",
    )
    verdict = pipeline.process_finding(finding)
    assert verdict.verdict == VerdictLabel.TRUE_POSITIVE
    assert verdict.calibrated_confidence is not None


def test_run_on_findings_processes_each_independently():
    pipeline = _build_pipeline()
    findings = [
        Finding(rule_id="r1", cwe_id="CWE-89", file_path="a.py", line=1, message="m1", code_snippet="x"),
        Finding(rule_id="r2", cwe_id="CWE-79", file_path="b.py", line=2, message="m2", code_snippet="y"),
    ]
    verdicts = pipeline.run_on_findings(findings)
    assert len(verdicts) == 2
    assert {v.finding_id for v in verdicts} == {f.finding_id for f in findings}


def test_pipeline_fail_open_on_orchestration_error(monkeypatch):
    pipeline = _build_pipeline()

    def broken_query(self, finding, top_k=3, cwe_filter=True):
        raise RuntimeError("simulated retrieval crash")

    monkeypatch.setattr(KnowledgeIndex, "query", broken_query)

    finding = Finding(rule_id="r1", cwe_id="CWE-89", file_path="a.py", line=1, message="m", code_snippet="x")
    verdict = pipeline.process_finding(finding)
    assert verdict.verdict == VerdictLabel.NEEDS_REVIEW
    assert verdict.fail_open is True


def test_eval_harness_scores_scan_run():
    finding = Finding(rule_id="r1", cwe_id="CWE-89", file_path="a.py", line=1, message="m", code_snippet="x")
    verdict = Verdict(
        finding_id=finding.finding_id,
        cwe_id="CWE-89",
        verdict=VerdictLabel.TRUE_POSITIVE,
        raw_confidence=0.9,
        calibrated_confidence=0.85,
        justification="j",
    )
    scan_run = ScanRun(repo_name="test/repo", findings=[finding], verdicts=[verdict])
    ground_truth = {finding.finding_id: True}

    results = score_scan_run(scan_run, ground_truth)
    assert results["precision"] == 1.0
    assert results["recall"] == 1.0
    assert results["n_findings_scored"] == 1
