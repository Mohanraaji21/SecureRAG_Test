"""
Expected Calibration Error (report section 3.2.1 / 5.1) -- the project's
primary novel evaluation metric, absent from every reviewed prior system.
"""

from __future__ import annotations

import numpy as np


def expected_calibration_error(
    confidences: np.ndarray,
    correct: np.ndarray,
    n_bins: int = 10,
) -> float:
    """Standard binned ECE: partitions [0,1] confidence into `n_bins` equal
    -width bins, and for each bin computes |avg_confidence - accuracy|,
    weighted by the fraction of samples falling in that bin.

    `confidences`: calibrated confidence scores in [0, 1].
    `correct`: 1.0 if the verdict matched ground truth, else 0.0.
    """
    confidences = np.asarray(confidences, dtype="float64")
    correct = np.asarray(correct, dtype="float64")
    if confidences.shape != correct.shape:
        raise ValueError("confidences and correct must be the same shape")
    if len(confidences) == 0:
        return 0.0

    bin_edges = np.linspace(0.0, 1.0, n_bins + 1)
    ece = 0.0
    n = len(confidences)

    for lo, hi in zip(bin_edges[:-1], bin_edges[1:]):
        in_bin = (confidences > lo) & (confidences <= hi)
        if lo == 0.0:
            in_bin = in_bin | (confidences == 0.0)
        count = int(in_bin.sum())
        if count == 0:
            continue
        bin_confidence = confidences[in_bin].mean()
        bin_accuracy = correct[in_bin].mean()
        ece += (count / n) * abs(bin_confidence - bin_accuracy)

    return float(ece)


def reliability_diagram_data(
    confidences: np.ndarray,
    correct: np.ndarray,
    n_bins: int = 10,
) -> list[dict]:
    """Per-bin (avg_confidence, accuracy, count) data for plotting the
    reliability diagram described in report Figure 5.2. Consumed later by
    the Phase 2 `/metrics/calibration` endpoint."""
    confidences = np.asarray(confidences, dtype="float64")
    correct = np.asarray(correct, dtype="float64")
    bin_edges = np.linspace(0.0, 1.0, n_bins + 1)
    rows = []
    for lo, hi in zip(bin_edges[:-1], bin_edges[1:]):
        in_bin = (confidences > lo) & (confidences <= hi)
        if lo == 0.0:
            in_bin = in_bin | (confidences == 0.0)
        count = int(in_bin.sum())
        rows.append(
            {
                "bin_range": [float(lo), float(hi)],
                "avg_confidence": float(confidences[in_bin].mean()) if count else None,
                "accuracy": float(correct[in_bin].mean()) if count else None,
                "count": count,
            }
        )
    return rows
