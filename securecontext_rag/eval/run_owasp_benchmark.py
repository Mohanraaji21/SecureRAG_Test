"""
Evaluation harness (report section 5.1-5.3).

Runs the TriagePipeline against a labeled dataset (OWASP Benchmark v1.2 or
a curated CVE set) and reports Precision, Recall, F1, False-Positive Rate,
and Expected Calibration Error against the target metrics in Table 5.2.

Expected label file format (JSON): a list of
  {"finding_id": "...", "ground_truth_is_vulnerable": true|false}
keyed by the same `finding_id` the pipeline assigned when Semgrep ran, OR
matched by (file_path, line) if you're scoring against an external label
set -- see `match_labels_by_location`.

This is a harness/skeleton: it does not ship OWASP Benchmark's Java test
corpus (that must be downloaded separately, see the report's citation
[12]), but the scoring logic is complete and unit-tested against
synthetic data in tests/test_pipeline.py.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from sklearn.metrics import precision_recall_fscore_support

from core.calibration.metrics import expected_calibration_error, reliability_diagram_data
from core.schemas.models import ScanRun, VerdictLabel


def match_labels_by_location(
    scan_run: ScanRun, labels: list[dict]
) -> list[tuple[str, bool]]:
    """Maps ground-truth labels to findings by (file_path, line) when an
    external benchmark's finding IDs don't line up with ours. Returns a
    list of (finding_id, ground_truth_is_vulnerable)."""
    loc_to_label = {(l["file_path"], l["line"]): l["ground_truth_is_vulnerable"] for l in labels}
    matched = []
    for finding in scan_run.findings:
        key = (finding.file_path, finding.line)
        if key in loc_to_label:
            matched.append((finding.finding_id, loc_to_label[key]))
    return matched


def score_scan_run(
    scan_run: ScanRun, ground_truth: dict[str, bool]
) -> dict:
    """`ground_truth`: finding_id -> True (real vulnerability) / False (false positive)."""
    y_true: list[int] = []
    y_pred: list[int] = []
    confidences: list[float] = []
    correct: list[float] = []

    verdict_by_finding = {v.finding_id: v for v in scan_run.verdicts}

    for finding_id, is_vuln in ground_truth.items():
        verdict = verdict_by_finding.get(finding_id)
        if verdict is None:
            continue
        # needs_review is treated as a predicted-positive (retained, not
        # discarded) for P/R purposes, matching the fail-open design intent.
        predicted_positive = verdict.verdict in (
            VerdictLabel.TRUE_POSITIVE,
            VerdictLabel.NEEDS_REVIEW,
        )
        y_true.append(1 if is_vuln else 0)
        y_pred.append(1 if predicted_positive else 0)

        confidence = verdict.calibrated_confidence
        if confidence is not None:
            was_correct = (predicted_positive == is_vuln)
            confidences.append(confidence)
            correct.append(1.0 if was_correct else 0.0)

    if not y_true:
        return {"error": "no ground-truth findings matched this scan run"}

    precision, recall, f1, _ = precision_recall_fscore_support(
        y_true, y_pred, average="binary", zero_division=0
    )

    y_true_arr = np.array(y_true)
    y_pred_arr = np.array(y_pred)
    false_positives = int(((y_pred_arr == 1) & (y_true_arr == 0)).sum())
    actual_negatives = int((y_true_arr == 0).sum())
    fpr = false_positives / actual_negatives if actual_negatives else 0.0

    ece = None
    if confidences:
        ece = expected_calibration_error(np.array(confidences), np.array(correct))

    return {
        "n_findings_scored": len(y_true),
        "precision": round(float(precision), 4),
        "recall": round(float(recall), 4),
        "f1": round(float(f1), 4),
        "false_positive_rate": round(fpr, 4),
        "expected_calibration_error": round(ece, 4) if ece is not None else None,
        "reliability_diagram": (
            reliability_diagram_data(np.array(confidences), np.array(correct))
            if confidences
            else None
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scan-run-json", required=True, help="Path to a saved ScanRun JSON")
    parser.add_argument("--labels-json", required=True, help="Path to ground-truth labels JSON")
    args = parser.parse_args()

    scan_run = ScanRun.model_validate(json.loads(Path(args.scan_run_json).read_text()))
    raw_labels = json.loads(Path(args.labels_json).read_text())
    ground_truth = {l["finding_id"]: l["ground_truth_is_vulnerable"] for l in raw_labels}

    results = score_scan_run(scan_run, ground_truth)
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
