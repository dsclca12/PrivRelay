"""Stateless score fusion and disagreement-aware routing for local SMS models."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from scipy.special import softmax


class CommitteePredictor:
    def __init__(self, models, *, classes, weights=None, mode="parallel",
                 review_threshold=0.0, margin_threshold=0.0, fast_threshold=0.95, temperatures=None):
        self.models = list(models)
        self.classes_ = list(classes)
        if not self.models or len(self.classes_) < 2 or len(set(self.classes_)) != len(self.classes_):
            raise ValueError("Committee needs members and distinct output classes")
        if mode not in {"parallel", "consensus", "cascade"}:
            raise ValueError("Unknown committee mode")
        if mode in {"consensus", "cascade"} and "uncertain" not in self.classes_:
            raise ValueError("Abstaining committees need an uncertain output")
        if mode == "cascade" and len(self.models) != 2:
            raise ValueError("Cascade requires a fast model and one reviewer")
        self.orders = []
        for model in self.models:
            labels = list(model.classes_)
            if len(labels) < 2 or len(set(labels)) != len(labels) or not set(labels) <= set(self.classes_):
                raise ValueError("Member classes must be a distinct subset of committee classes")
            self.orders.append([self.classes_.index(label) for label in labels])
        values = np.asarray(weights if weights is not None else [1.0] * len(self.models), dtype=float)
        if (values.shape != (len(self.models),) or not np.isfinite(values).all() or (values < 0).any()
                or not np.isfinite(values.sum()) or values.sum() <= 0):
            raise ValueError("Weights must be finite, nonnegative and have positive total mass")
        self.weights = values / values.sum()
        self.temperatures = np.asarray(temperatures if temperatures is not None else [1.0] * len(self.models), dtype=float)
        if (self.temperatures.shape != (len(self.models),) or not np.isfinite(self.temperatures).all()
                or (self.temperatures < .05).any() or (self.temperatures > 20).any()):
            raise ValueError("Member temperatures must be finite values in [0.05, 20]")
        for value in (review_threshold, margin_threshold, fast_threshold):
            if not np.isfinite(value) or not 0 <= value <= 1:
                raise ValueError("Committee thresholds must be in [0, 1]")
        self.mode = mode
        self.review_threshold = review_threshold
        self.margin_threshold = margin_threshold
        self.fast_threshold = fast_threshold

    def _member(self, index, texts):
        values = np.asarray(self.models[index].predict_proba(texts), dtype=float)
        if (values.shape != (len(texts), len(self.orders[index])) or not np.isfinite(values).all()
                or (values < 0).any() or (values > 1).any()
                or not np.allclose(values.sum(axis=1), 1.0, atol=1e-5)):
            raise ValueError("Member returned invalid probabilities")
        if self.temperatures[index] != 1.0:
            values = softmax(np.log(np.clip(values, 1e-12, 1.0)) / self.temperatures[index], axis=1)
        aligned = np.zeros((len(texts), len(self.classes_)))
        aligned[:, self.orders[index]] = values
        return aligned

    def predict_with_details(self, texts):
        count = len(texts)
        if not count:
            return {"probabilities": np.empty((0, len(self.classes_))),
                    **{key: np.zeros(0, dtype=bool) for key in ("review_mask", "abstain_mask", "disagreement_mask", "routed_mask")}}
        if self.mode == "cascade":
            fast = self._member(0, texts)
            fast_labels = np.asarray(self.classes_)[fast.argmax(axis=1)]
            sorted_fast = np.sort(fast, axis=1)
            routed = ((fast.max(axis=1) < max(self.fast_threshold, self.review_threshold))
                      | (sorted_fast[:, -1] - sorted_fast[:, -2] < self.margin_threshold)
                      | ~np.isin(fast_labels, ["personal", "otp", "service", "transaction"]))
            values = fast.copy()
            disagreement = np.zeros(count, dtype=bool)
            if routed.any():
                reviewer = self._member(1, [text for text, route in zip(texts, routed) if route])
                values[routed] = self.weights[0] * fast[routed] + self.weights[1] * reviewer
                disagreement[routed] = fast[routed].argmax(axis=1) != reviewer.argmax(axis=1)
        else:
            members = [self._member(i, texts) for i in range(len(self.models))]
            values = sum(weight * member for weight, member in zip(self.weights, members))
            votes = np.asarray([member.argmax(axis=1) for member in members])
            disagreement = np.any(votes != votes[0], axis=0)
            routed = np.full(count, len(self.models) > 1, dtype=bool)
        sorted_values = np.sort(values, axis=1)
        review = (disagreement | (values.max(axis=1) < self.review_threshold)
                  | (sorted_values[:, -1] - sorted_values[:, -2] < self.margin_threshold))
        if "uncertain" in self.classes_:
            review |= values.argmax(axis=1) == self.classes_.index("uncertain")
        return {"probabilities": values, "review_mask": review,
                "abstain_mask": review.copy() if self.mode != "parallel" else np.zeros(count, dtype=bool),
                "disagreement_mask": disagreement, "routed_mask": routed}

    def predict_proba(self, texts):
        return self.predict_with_details(texts)["probabilities"]


def load_ensemble_bundle(path):
    from .predict import load_model

    root = Path(path).resolve()
    metadata = json.loads((root / "metadata.json").read_text(encoding="utf-8"))
    if metadata.get("model_type") != "ensemble":
        raise ValueError("Not an ensemble artifact")
    components = []
    for member in metadata["members"]:
        relative = Path(member["path"])
        target = (root / relative).resolve()
        if relative.is_absolute() or not target.is_relative_to(root) or target == root:
            raise ValueError("Ensemble members must stay inside their artifact directory")
        bundle = load_model(target)
        if list(bundle["classes"]) != list(bundle["model"].classes_):
            raise ValueError("Member metadata class order does not match predictor")
        components.append(bundle["model"])
    predictor = CommitteePredictor(components, classes=metadata["classes"], **metadata["committee"])
    # Member calibration does not establish calibration of their fusion.
    return {**metadata, "model": predictor, "confidence_calibrated": False}
