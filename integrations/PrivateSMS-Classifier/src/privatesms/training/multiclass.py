"""Local seven-category sparse models and source-aware training weights."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import math
import unicodedata

import numpy as np
from scipy.special import softmax
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.naive_bayes import ComplementNB, MultinomialNB
from sklearn.svm import LinearSVC

from privatesms.text_normalization import normalize_texts


CATEGORIES = ["marketing", "otp", "personal", "service", "suspicious", "transaction", "uncertain"]


def normalize_sparse_texts(texts):
    # Match the dataset loader's Unicode normalization at online inference.
    return normalize_texts([unicodedata.normalize("NFKC", text).strip() for text in texts])


@dataclass(frozen=True)
class SparseConfig:
    ngram_min: int = 2
    ngram_max: int = 5
    classifier: str = "logistic"
    c: float = 4.0
    ai_weight: float = 0.3
    uncertain_weight: float = 1.0


def source_balanced_weights(labels, sources, *, ai_weight: float, uncertain_weight: float = 1.0) -> np.ndarray:
    """Balance classes after applying trust weights, without cancelling source trust.

    Human labels weigh 1; weak labels weigh ai_weight. Unlike class_weight on
    raw counts, this keeps each class's total effective loss mass equal when
    sources have very different class distributions. uncertain_weight can
    reduce the loss mass of the weakly supported ambiguous category.
    """
    if not math.isfinite(ai_weight) or not 0 < ai_weight <= 1:
        raise ValueError("ai_weight must be in (0, 1]")
    if not math.isfinite(uncertain_weight) or not 0 < uncertain_weight <= 1:
        raise ValueError("uncertain_weight must be in (0, 1]")
    if not labels or len(labels) != len(sources):
        raise ValueError("labels and sources must have matching non-empty rows")
    if any(source not in {"human", "ai"} for source in sources):
        raise ValueError("sources must be human or ai")
    base = np.asarray([1.0 if source == "human" else ai_weight for source in sources])
    mass = defaultdict(float)
    for label, weight in zip(labels, base):
        mass[label] += weight
    # Preserve the absolute regularization scale across trust-weight settings.
    weights = np.asarray([weight / mass[label] * (uncertain_weight if label == "uncertain" else 1.0)
                          for label, weight in zip(labels, base)])
    return weights * len(labels) / weights.sum()


class OneVsRestLogistic:
    """Sparse binary liblinear fits avoid a large dense multiclass optimizer."""
    def __init__(self, *, c: float, seed: int):
        self.c = c
        self.seed = seed

    def fit(self, matrix, labels, *, sample_weight):
        self.classes_ = np.asarray(sorted(set(labels)))
        targets = np.asarray(labels)
        self.estimators_ = []
        for label in self.classes_:
            model = LogisticRegression(C=self.c, solver="liblinear", max_iter=1000, random_state=self.seed)
            model.fit(matrix, targets == label, sample_weight=sample_weight)
            self.estimators_.append(model)
        return self

    def predict_proba(self, matrix):
        probabilities = np.column_stack([model.predict_proba(matrix)[:, 1] for model in self.estimators_])
        probabilities = np.clip(probabilities, 1e-12, 1.0)
        return probabilities / probabilities.sum(axis=1, keepdims=True)

    def predict(self, matrix):
        return self.classes_[self.predict_proba(matrix).argmax(axis=1)]


def make_vectorizer(config: SparseConfig):
    return TfidfVectorizer(
        analyzer="char", ngram_range=(config.ngram_min, config.ngram_max),
        sublinear_tf=True, min_df=1, max_features=300_000,
    )


def fit_classifier(matrix, labels, sources, config: SparseConfig, *, seed: int):
    if not math.isfinite(config.c) or config.c <= 0:
        raise ValueError("C must be positive and finite")
    if config.classifier == "logistic":
        classifier = OneVsRestLogistic(c=config.c, seed=seed)
    elif config.classifier == "svm":
        classifier = LinearSVC(C=config.c, dual="auto", max_iter=5000, random_state=seed)
    elif config.classifier == "complement_nb":
        classifier = ComplementNB(alpha=config.c, norm=True)
    elif config.classifier == "multinomial_nb":
        classifier = MultinomialNB(alpha=config.c)
    else:
        raise ValueError(f"Unsupported classifier: {config.classifier}")
    classifier.fit(matrix, labels, sample_weight=source_balanced_weights(
        labels, sources, ai_weight=config.ai_weight, uncertain_weight=config.uncertain_weight))
    return classifier


class SparseSmsPredictor:
    def __init__(self, vectorizer, classifier):
        self.vectorizer = vectorizer
        self.classifier = classifier
        self.classes_ = list(classifier.classes_)

    def predict_proba(self, texts):
        if not texts:
            return np.empty((0, len(self.classes_)))
        matrix = self.vectorizer.transform(normalize_sparse_texts(texts))
        if hasattr(self.classifier, "predict_proba"):
            return self.classifier.predict_proba(matrix)
        # Only a score normalization: metadata must not claim calibration.
        return softmax(self.classifier.decision_function(matrix), axis=1)


def fit_sparse_model(texts, labels, sources, config: SparseConfig, *, seed: int = 42):
    if set(labels) != set(CATEGORIES):
        raise ValueError("Seven-category training requires all seven labels")
    vectorizer = make_vectorizer(config)
    matrix = vectorizer.fit_transform(normalize_sparse_texts(texts))
    return SparseSmsPredictor(vectorizer, fit_classifier(matrix, labels, sources, config, seed=seed))
