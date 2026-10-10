"""
Temperature-scaling calibration layer (report section 3.2.1 / 4.2.3).

Fits a single scalar temperature T > 0 on a labeled validation set by
minimizing negative log-likelihood, then applies it to convert raw LLM
confidence into a calibrated confidence. Conformal prediction is noted in
the report (section 5.6) as a planned fallback refinement if temperature
scaling proves too coarse -- not implemented in Phase 1, left as a clean
extension point (`Calibrator` could grow a second implementation).
"""

from __future__ import annotations

import numpy as np
from scipy.optimize import minimize_scalar

_EPS = 1e-6


def _logit(p: np.ndarray) -> np.ndarray:
    p = np.clip(p, _EPS, 1 - _EPS)
    return np.log(p / (1 - p))


def _sigmoid(z: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-z))


class TemperatureScaler:
    """Binary-outcome temperature scaling: treats `raw_confidence` as the
    model's probability of being correct, transforms to logit space,
    divides by a fitted temperature T, and maps back through the sigmoid.

    T > 1 flattens (reduces) overconfident scores toward 0.5.
    T < 1 sharpens scores away from 0.5.
    T == 1 is a no-op (identity calibration).
    """

    def __init__(self) -> None:
        self.temperature: float = 1.0
        self._is_fitted: bool = False

    def fit(self, raw_confidences: np.ndarray, correct: np.ndarray) -> "TemperatureScaler":
        raw_confidences = np.asarray(raw_confidences, dtype="float64")
        correct = np.asarray(correct, dtype="float64")
        if len(raw_confidences) == 0:
            raise ValueError("cannot fit calibrator on an empty validation set")

        logits = _logit(raw_confidences)

        def nll(temperature: float) -> float:
            if temperature <= 1e-3:
                return np.inf
            probs = _sigmoid(logits / temperature)
            probs = np.clip(probs, _EPS, 1 - _EPS)
            return -float(np.mean(correct * np.log(probs) + (1 - correct) * np.log(1 - probs)))

        result = minimize_scalar(nll, bounds=(1e-2, 50.0), method="bounded")
        self.temperature = float(result.x)
        self._is_fitted = True
        return self

    def calibrate(self, raw_confidence: float) -> float:
        """Applies the fitted temperature to a single raw confidence score.
        If `fit()` hasn't been called yet, acts as identity (T=1) -- this is
        intentional so the pipeline is usable before enough labeled data
        exists to fit a calibrator (early in the project timeline)."""
        logit = _logit(np.array([raw_confidence]))[0]
        calibrated = _sigmoid(np.array([logit / self.temperature]))[0]
        return float(calibrated)

    def calibrate_batch(self, raw_confidences: np.ndarray) -> np.ndarray:
        logits = _logit(np.asarray(raw_confidences, dtype="float64"))
        return _sigmoid(logits / self.temperature)

    def to_dict(self) -> dict:
        return {"temperature": self.temperature, "is_fitted": self._is_fitted}

    @classmethod
    def from_dict(cls, data: dict) -> "TemperatureScaler":
        scaler = cls()
        scaler.temperature = data["temperature"]
        scaler._is_fitted = data.get("is_fitted", True)
        return scaler
