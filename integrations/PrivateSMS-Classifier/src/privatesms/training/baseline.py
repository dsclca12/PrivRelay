from __future__ import annotations

import os
import tempfile
from pathlib import Path

import joblib
import numpy as np
from sklearn.base import clone
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import FunctionTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.pipeline import Pipeline

from privatesms.datasets import SmsDataset, split_by_template
from privatesms.inference.calibration import CalibratedPredictor
from privatesms.text_normalization import normalize_texts


def _fit_grouped_calibrator(
    estimator,
    texts: list[str],
    labels: list[str],
    groups: list[str],
    *,
    seed: int,
    sample_weights: list[float] | None = None,
):
    group_counts = {
        label: len({group for group, target in zip(groups, labels) if target == label})
        for label in set(labels)
    }
    folds = min(5, min(group_counts.values(), default=0))
    if folds < 2:
        return None
    if sample_weights is not None and len(sample_weights) != len(texts):
        raise ValueError("sample_weights must match the training rows")

    splitter = StratifiedGroupKFold(n_splits=folds, shuffle=True, random_state=seed)
    oof_scores = None
    for train_rows, heldout_rows in splitter.split(texts, labels, groups):
        fold_model = clone(estimator)
        fit_options = {}
        if sample_weights is not None:
            fit_options["classifier__sample_weight"] = np.asarray([sample_weights[i] for i in train_rows], dtype=float)
        fold_model.fit([texts[i] for i in train_rows], [labels[i] for i in train_rows], **fit_options)
        scores = np.asarray(fold_model.decision_function([texts[i] for i in heldout_rows]))
        if scores.ndim == 1:
            scores = scores.reshape(-1, 1)
        if oof_scores is None:
            oof_scores = np.empty((len(texts), scores.shape[1]), dtype=float)
        oof_scores[heldout_rows] = scores

    calibrator = LogisticRegression(max_iter=1000, solver="lbfgs")
    calibrator.fit(oof_scores, labels, sample_weight=sample_weights)
    return calibrator


def train_baseline(
    dataset: SmsDataset,
    *,
    model_path: str | Path,
    seed: int = 42,
    splits: dict[str, list[int]] | None = None,
    synthetic_loss_share: float | None = None,
) -> tuple[Pipeline, dict[str, list[int]]]:
    splits = splits or split_by_template(dataset, seed=seed)
    train_indices = splits["train"]
    model = Pipeline([
        ("normalize_otp", FunctionTransformer(normalize_texts, validate=False)),
        ("tfidf", TfidfVectorizer(analyzer="char", ngram_range=(2, 5), min_df=1, sublinear_tf=True, max_features=300_000)),
        ("classifier", LogisticRegression(class_weight="balanced", max_iter=1000, random_state=seed, solver="lbfgs")),
    ])
    train_texts = [dataset.texts[i] for i in train_indices]
    train_labels = [dataset.labels[i] for i in train_indices]
    train_groups = [dataset.template_ids[i] for i in train_indices]
    sample_weights = None
    if synthetic_loss_share is not None:
        if not 0 < synthetic_loss_share < 1:
            raise ValueError("synthetic_loss_share must be between 0 and 1, exclusive")
        public_counts: dict[str, int] = {}
        supplement_counts: dict[str, int] = {}
        for index in train_indices:
            label = dataset.labels[index]
            is_supplement = dataset.training_only[index] or dataset.synthetic_flags[index]
            counts = supplement_counts if is_supplement else public_counts
            counts[label] = counts.get(label, 0) + 1
        missing_public_classes = sorted(label for label in supplement_counts if not public_counts.get(label))
        if missing_public_classes:
            raise ValueError(
                "Per-class synthetic loss weighting requires a public training example for every supplemental label; "
                f"missing {missing_public_classes}"
            )
        class_weights = {
            label: (synthetic_loss_share / (1 - synthetic_loss_share)) * public_counts[label] / count
            for label, count in supplement_counts.items()
        }
        sample_weights = [
            class_weights[dataset.labels[index]]
            if dataset.training_only[index] or dataset.synthetic_flags[index]
            else 1.0
            for index in train_indices
        ]
    calibrator = _fit_grouped_calibrator(
        model, train_texts, train_labels, train_groups, seed=seed, sample_weights=sample_weights
    )
    fit_options = {"classifier__sample_weight": np.asarray(sample_weights, dtype=float)} if sample_weights is not None else {}
    model.fit(train_texts, train_labels, **fit_options)
    if calibrator is not None:
        model = CalibratedPredictor(model, calibrator)
    target = Path(model_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    bundle = {
        "model": model,
        "classes": list(model.classes_),
        "version": "baseline-char-tfidf-lr-v1",
        "decision_threshold": 0.5,
        "confidence_calibrated": calibrator is not None,
        "calibration_method": "grouped-oof-logistic" if calibrator is not None else None,
        "synthetic_loss_share_per_class": synthetic_loss_share,
        "training_weight_policy": "equal-effective-supplement-loss-share-per-class" if synthetic_loss_share is not None else "default-unweighted-samples",
    }
    fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    temporary = Path(temp_name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as handle:
            joblib.dump(bundle, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return model, splits
