from __future__ import annotations

import math

from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score, precision_score, recall_score


RISK_CLASSES = {"spam", "marketing", "suspicious"}
BENIGN_CLASSES = {"ham", "personal", "otp", "service", "transaction"}


def _spam_scores(model, texts: list[str]) -> list[float]:
    classes = list(model.classes_)
    risk_indices = [i for i, label in enumerate(classes) if label in RISK_CLASSES]
    if not risk_indices:
        raise ValueError("Model classes must include spam, marketing, or suspicious")
    return [float(sum(row[i] for i in risk_indices)) for row in model.predict_proba(texts)]


def choose_threshold(model, texts: list[str], labels: list[str], *, ham_fpr_limit: float = 0.01) -> dict:
    if not math.isfinite(ham_fpr_limit) or not 0 <= ham_fpr_limit <= 1:
        raise ValueError("ham_fpr_limit must be between 0 and 1")
    scores = _spam_scores(model, texts)
    benign_count = sum(label in BENIGN_CLASSES for label in labels)
    if benign_count == 0:
        raise ValueError("Validation set must contain benign examples")
    risk_count = sum(label in RISK_CLASSES for label in labels)
    candidates = sorted({0.0, 1.0, *scores})
    acceptable = []
    for threshold in candidates:
        predictions = ["spam" if score >= threshold else "ham" for score in scores]
        fpr = sum(p == "spam" and y in BENIGN_CLASSES for p, y in zip(predictions, labels)) / benign_count
        risk_recall = sum(p == "spam" and y in RISK_CLASSES for p, y in zip(predictions, labels)) / risk_count if risk_count else 0.0
        if fpr <= ham_fpr_limit:
            acceptable.append((risk_recall, -threshold, threshold, fpr))
    if acceptable:
        recall, _, threshold, fpr = max(acceptable)
        return {"threshold": threshold, "benign_false_positive_rate": fpr, "spam_recall": recall, "ham_fpr_limit": ham_fpr_limit, "target_met": True}
    threshold = math.nextafter(max(scores, default=1.0), math.inf)
    return {"threshold": threshold, "benign_false_positive_rate": 0.0, "spam_recall": 0.0, "ham_fpr_limit": ham_fpr_limit, "target_met": False}


def evaluate(model, texts: list[str], labels: list[str], *, threshold: float = 0.5, sample_ids: list[int] | None = None, category_decision: str = "risk_threshold") -> dict:
    if not math.isfinite(threshold) or not 0 <= threshold <= 1:
        raise ValueError("threshold must be between 0 and 1")
    if not texts or len(texts) != len(labels):
        raise ValueError("texts and labels must have the same non-zero length")
    if sample_ids is not None and len(sample_ids) != len(labels):
        raise ValueError("sample_ids must match labels")
    if category_decision not in {"risk_threshold", "argmax"}:
        raise ValueError("category_decision must be risk_threshold or argmax")
    classes = list(model.classes_)
    details = model.predict_with_details(texts) if hasattr(model, "predict_with_details") else None
    probabilities = details["probabilities"] if details is not None else model.predict_proba(texts)
    risk_indices = [i for i, label in enumerate(classes) if label in RISK_CLASSES]
    if not risk_indices:
        raise ValueError("Model classes must include spam, marketing, or suspicious")
    scores = [float(sum(row[i] for i in risk_indices)) for row in probabilities]
    binary = set(classes) <= {"ham", "spam"}
    if binary:
        predictions = ["spam" if score >= threshold else "ham" for score in scores]
    elif category_decision == "argmax":
        predictions = [classes[max(range(len(classes)), key=lambda i: row[i])] for row in probabilities]
    else:
        benign_indices = [i for i in range(len(classes)) if i not in risk_indices]
        predictions = []
        for row, score in zip(probabilities, scores):
            candidates = risk_indices if score >= threshold else benign_indices
            if not candidates:
                candidates = list(range(len(classes)))
            predictions.append(classes[max(candidates, key=lambda i: row[i])])
    if details is not None:
        predictions = ["uncertain" if abstain else category for category, abstain in zip(predictions, details["abstain_mask"])]
    risk_predictions = [score >= threshold and not ((category_decision == "argmax" or details is not None) and category == "uncertain")
                        for score, category in zip(scores, predictions)]
    error_indices = [i for i, (gold, predicted) in enumerate(zip(labels, predictions)) if gold != predicted]
    index_lookup = list(range(len(labels))) if sample_ids is None else sample_ids
    class_labels = [label for label in ("ham", "spam", "personal", "otp", "service", "transaction", "marketing", "suspicious", "uncertain") if label in set(labels) | set(classes)]
    scored_labels = sorted(set(labels) | set(predictions))
    calibration_bins = 10
    confidences = [float(max(row)) for row in probabilities]
    correctness = [classes[int(max(range(len(row)), key=lambda i: row[i]))] == label for row, label in zip(probabilities, labels)]
    ece = 0.0
    for bin_index in range(calibration_bins):
        low = bin_index / calibration_bins
        high = (bin_index + 1) / calibration_bins
        members = [i for i, confidence in enumerate(confidences) if low <= confidence < high or (bin_index == calibration_bins - 1 and confidence == 1.0)]
        if members:
            mean_confidence = sum(confidences[i] for i in members) / len(members)
            mean_accuracy = sum(correctness[i] for i in members) / len(members)
            ece += len(members) / len(labels) * abs(mean_confidence - mean_accuracy)
    brier_score = sum(
        sum((float(row[i]) - float(classes[i] == label)) ** 2 for i in range(len(classes)))
        for row, label in zip(probabilities, labels)
    ) / len(labels)
    benign_count = sum(label in BENIGN_CLASSES for label in labels)
    benign_fp = sum(pred and label in BENIGN_CLASSES for pred, label in zip(risk_predictions, labels))
    risk_count = sum(label in RISK_CLASSES for label in labels)
    risk_tp = sum(pred and label in RISK_CLASSES for pred, label in zip(risk_predictions, labels))
    important_fpr = {}
    for label in ("personal", "otp", "service", "transaction", "ham"):
        count = sum(y == label for y in labels)
        if count:
            important_fpr[label] = sum(pred and y == label for pred, y in zip(risk_predictions, labels)) / count
    result = {
        "threshold": threshold,
        "category_decision": category_decision,
        "samples": len(labels),
        "error_sample_indices": [int(index_lookup[i]) for i in error_indices],
        "accuracy": accuracy_score(labels, predictions),
        "macro_f1": f1_score(labels, predictions, labels=scored_labels, average="macro", zero_division=0),
        "probability_calibration": {
            "brier_score": brier_score,
            "top_label_ece": ece,
            "bins": calibration_bins,
        },
        "ham_false_positive_rate": important_fpr.get("ham"),
        "important_category_false_positive_rate": important_fpr,
        "risk_false_positive_rate": benign_fp / benign_count if benign_count else None,
        "risk_recall": risk_tp / risk_count if risk_count else None,
        "spam_precision": precision_score([1 if y in RISK_CLASSES else 0 for y in labels], [int(p) for p in risk_predictions], zero_division=0),
        "spam_recall": risk_tp / risk_count if risk_count else None,
        "confusion_matrix_labels": class_labels,
        "confusion_matrix": confusion_matrix(labels, predictions, labels=class_labels).tolist(),
        "per_class": classification_report(labels, predictions, labels=class_labels, output_dict=True, zero_division=0),
    }
    if details is not None:
        accepted = [i for i, review in enumerate(details["review_mask"]) if not review and predictions[i] != "uncertain"]
        accepted_benign = [i for i in accepted if labels[i] in BENIGN_CLASSES]
        result["selective_policy"] = {
            "accepted_samples": len(accepted), "coverage": len(accepted) / len(labels),
            "accepted_accuracy": sum(predictions[i] == labels[i] for i in accepted) / len(accepted) if accepted else None,
            "accepted_benign_samples": len(accepted_benign),
            "accepted_risk_false_positive_rate": sum(risk_predictions[i] for i in accepted_benign) / len(accepted_benign) if accepted_benign else None,
            "review_rate": 1.0 - len(accepted) / len(labels),
            "disagreement_rate": sum(bool(x) for x in details["disagreement_mask"]) / len(labels),
            "reviewer_call_rate": sum(bool(x) for x in details["routed_mask"]) / len(labels),
            "scope": "model routing policy only; artifact-level mandatory human review still applies",
        }
    return result
