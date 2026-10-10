import numpy as np

from core.calibration.metrics import expected_calibration_error, reliability_diagram_data
from core.calibration.temperature_scaling import TemperatureScaler


def test_unfitted_scaler_is_identity():
    scaler = TemperatureScaler()
    assert abs(scaler.calibrate(0.7) - 0.7) < 1e-6


def test_fit_reduces_overconfidence():
    # Simulate an overconfident model: it says 0.95 confidence but is only
    # right 60% of the time. After fitting, calibrated confidence for a
    # 0.95 raw score should shrink toward 0.6.
    rng = np.random.default_rng(0)
    n = 2000
    raw_confidences = np.full(n, 0.95)
    correct = (rng.random(n) < 0.6).astype(float)

    scaler = TemperatureScaler().fit(raw_confidences, correct)
    calibrated = scaler.calibrate(0.95)

    assert scaler.temperature > 1.0  # should flatten an overconfident model
    assert calibrated < 0.95
    assert abs(calibrated - 0.6) < 0.08


def test_ece_perfect_calibration_is_near_zero():
    # A confidence-0.9 bin where accuracy really is 90% is perfectly
    # calibrated: avg_confidence (0.9) == accuracy (0.9) => 0 contribution.
    confidences = np.full(10, 0.9)
    correct = np.array([1.0] * 9 + [0.0])  # exactly 90% correct
    ece = expected_calibration_error(confidences, correct, n_bins=10)
    assert ece < 0.01


def test_ece_detects_overconfidence():
    confidences = np.full(100, 0.95)
    correct = np.zeros(100)  # model is always wrong despite high confidence
    ece = expected_calibration_error(confidences, correct, n_bins=10)
    assert ece > 0.9


def test_reliability_diagram_data_shape():
    confidences = np.array([0.05, 0.55, 0.95])
    correct = np.array([0.0, 1.0, 1.0])
    rows = reliability_diagram_data(confidences, correct, n_bins=10)
    assert len(rows) == 10
    non_empty = [r for r in rows if r["count"] > 0]
    assert len(non_empty) == 3
