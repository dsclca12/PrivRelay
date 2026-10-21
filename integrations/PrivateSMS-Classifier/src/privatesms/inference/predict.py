from __future__ import annotations

import math
import json
from pathlib import Path

import joblib


def load_model(path: str | Path) -> dict:
    target = Path(path)
    if target.is_dir():
        if (target / "model.onnx").is_file() or (target / "model.int8.onnx").is_file():
            from .onnx import load_onnx_bundle

            return load_onnx_bundle(target)
        metadata = json.loads((target / "metadata.json").read_text(encoding="utf-8"))
        if metadata.get("model_type") == "ensemble":
            from .ensemble import load_ensemble_bundle

            return load_ensemble_bundle(target)
        from .transformer import load_transformer_bundle

        return load_transformer_bundle(target)
    return joblib.load(target)


def predict(
    bundle: dict,
    text: str,
    *,
    threshold: float | None = None,
    review_confidence_threshold: float | None = None,
) -> dict:
    model = bundle["model"]
    classes = list(bundle["classes"])
    threshold = bundle.get("decision_threshold", 0.5) if threshold is None else threshold
    if not math.isfinite(threshold) or not 0 <= threshold <= 1:
        raise ValueError("threshold must be between 0 and 1")
    details = model.predict_with_details([text]) if hasattr(model, "predict_with_details") else None
    probabilities = (details["probabilities"] if details is not None else model.predict_proba([text]))[0]
    risk_indices = [i for i, label in enumerate(classes) if label in {"spam", "marketing", "suspicious"}]
    if not risk_indices:
        raise ValueError("Model does not contain a spam-risk class")
    spam_score = float(sum(probabilities[i] for i in risk_indices))
    is_spam = spam_score >= threshold
    binary = set(classes) <= {"ham", "spam"}
    confidence = float(max(probabilities))
    category_decision = bundle.get("category_decision", "risk_threshold")
    if category_decision not in {"risk_threshold", "argmax"}:
        raise ValueError("category_decision must be risk_threshold or argmax")
    if binary:
        predicted_category = "spam" if spam_score >= threshold else "ham"
    elif category_decision == "argmax":
        # Business intent and a tuned blocking threshold answer different
        # questions. New category models keep their most probable label.
        predicted_category = classes[max(range(len(classes)), key=lambda i: probabilities[i])]
        if predicted_category == "uncertain":
            is_spam = False
    else:
        category_indices = risk_indices if is_spam else [i for i in range(len(classes)) if i not in risk_indices]
        if not category_indices:
            category_indices = list(range(len(classes)))
        predicted_category = classes[max(category_indices, key=lambda i: probabilities[i])]
    review_threshold = bundle.get("review_confidence_threshold", 0.6) if review_confidence_threshold is None else review_confidence_threshold
    if not math.isfinite(review_threshold) or not 0 <= review_threshold <= 1:
        raise ValueError("review_confidence_threshold must be between 0 and 1")
    # Six-way business classifiers can expose the seventh API outcome as a
    # confidence-based abstention. Keep this opt-in so legacy models retain
    # their existing behavior; the preview model deliberately marks its
    # confidence as uncalibrated, which also prevents automatic blocking.
    abstain_threshold = bundle.get("abstain_confidence_threshold")
    if abstain_threshold is not None:
        if binary or "uncertain" in classes:
            raise ValueError("abstention threshold is only valid for multiclass models without an uncertain output class")
        if not math.isfinite(abstain_threshold) or not 0 <= abstain_threshold <= 1:
            raise ValueError("abstain_confidence_threshold must be between 0 and 1")
        if confidence < abstain_threshold:
            predicted_category = "uncertain"
    if details is not None and details["abstain_mask"][0]:
        predicted_category = "uncertain"
        is_spam = False
    return {
        "category": predicted_category,
        "is_spam": is_spam,
        "spam_score": spam_score,
        "confidence": confidence,
        "confidence_calibrated": bool(bundle.get("confidence_calibrated", False)),
        "needs_review": (
            predicted_category == "uncertain"
            or confidence < review_threshold
            or bool(bundle.get("always_requires_review", False))
            or (details is not None and bool(details["review_mask"][0]))
            or (
                not binary and category_decision == "argmax"
                and (predicted_category in {"marketing", "suspicious"}) != is_spam
            )
        ),
        "model_version": bundle["version"],
    }
