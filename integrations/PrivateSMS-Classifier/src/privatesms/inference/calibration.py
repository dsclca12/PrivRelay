from __future__ import annotations


class CalibratedPredictor:
    """Apply a logistic calibration map to an estimator's decision scores."""

    def __init__(self, estimator, calibrator):
        self.estimator = estimator
        self.calibrator = calibrator
        self.classes_ = list(estimator.classes_)

    def decision_function(self, texts):
        return self.estimator.decision_function(texts)

    def predict_proba(self, texts):
        import numpy as np

        scores = np.asarray(self.estimator.decision_function(texts))
        if scores.ndim == 1:
            scores = scores.reshape(-1, 1)
        return self.calibrator.predict_proba(scores)
