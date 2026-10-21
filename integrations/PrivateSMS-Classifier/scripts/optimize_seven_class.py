"""Select and package a real seven-class model using template-grouped nested CV.

Only local files are read. AI labels are training-only; all scores use human
labels. No SMS text is written to reports and no registry pointer is changed.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import random
import sys
import tempfile
import time

import joblib
import numpy as np
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score
from threadpoolctl import threadpool_limits

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from privatesms.datasets import load_dataset, normalize_text, prepare_dataset  # noqa: E402
from privatesms.datasets.loaders import _merge_near_duplicate_templates  # noqa: E402
from privatesms.evaluation import evaluate  # noqa: E402
from privatesms.training.multiclass import (  # noqa: E402
    CATEGORIES, SparseConfig, fit_classifier, fit_sparse_model, make_vectorizer, normalize_sparse_texts,
)


def private_json(path: Path, value):
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        # Publish a complete report atomically, while refusing replacement.
        os.link(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def prepare_corpora(human_path: Path, ai_paths: list[Path]):
    # The generic loader also supports teacher data; the evaluation entrypoint
    # must separately establish that every holdout label is human-confirmed.
    records = [json.loads(line) for line in human_path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    if not records or any(row.get("human_verified") is not True or row.get("source") != "human" for row in records):
        raise ValueError("Evaluation input must contain only explicitly human-verified labels")
    human, human_report = load_dataset(human_path, label_column="category", include_synthetic=True, include_feedback=True)
    if set(human.labels) - set(CATEGORIES):
        raise ValueError("Unsupported human category")
    rows = []
    for path in ai_paths:
        data, _ = load_dataset(path, label_column="category", include_synthetic=True, include_feedback=True, include_teacher_data=True)
        rows.extend((text, label, True, data.synthetic_flags[i], "ai")
                    for i, (text, label) in enumerate(zip(data.texts, data.labels)) if label in CATEGORIES)
    # Cluster jointly across sources: separately computed near-duplicate IDs
    # can differ, so comparing two sets of hashes alone does not isolate them.
    groups = defaultdict(list)
    for text, label in zip(human.texts, human.labels):
        groups[normalize_text(text, template=True)].append((text, label, False, True, "human"))
    for row in rows:
        groups[normalize_text(row[0], template=True)].append(row)
    clusters, merges = _merge_near_duplicate_templates(groups)
    overlaps = {row[0] for cluster in clusters.values() if any(not row[2] for row in cluster)
                for row in cluster if row[2]}
    ai, ai_report = prepare_dataset(row for row in rows if row[0] not in overlaps)
    if set(ai.labels) != set(CATEGORIES):
        raise ValueError("AI training data must cover all seven categories")
    return human, ai, {
        "human": asdict(human_report), "ai": asdict(ai_report),
        "ai_removed_for_human_overlap": len(overlaps), "cross_source_near_duplicate_merges": merges,
        "source_sha256": {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in [human_path, *ai_paths]},
    }


def grouped_folds(dataset, indices, count: int, seed: int):
    """Stratify template groups; rare classes are evaluated without duplication."""
    by_label = defaultdict(lambda: defaultdict(list))
    for i in indices:
        by_label[dataset.labels[i]][dataset.template_ids[i]].append(i)
    assigned = [[] for _ in range(count)]
    rng = random.Random(seed)
    for label in sorted(by_label):
        groups = list(by_label[label].values())
        rng.shuffle(groups)
        groups.sort(key=len, reverse=True)
        loads = [0] * count
        for group in groups:
            fold = min(range(count), key=lambda f: (loads[f], len(assigned[f]), f))
            assigned[fold].extend(group)
            loads[fold] += len(group)
    universe = set(indices)
    for heldout in assigned:
        test = sorted(heldout)
        train = sorted(universe - set(test))
        if not test or set(dataset.template_ids[i] for i in train) & set(dataset.template_ids[i] for i in test):
            raise ValueError("Empty fold or template overlap")
        yield train, test


def training_rows(human, ai, indices):
    return (
        [human.texts[i] for i in indices] + ai.texts,
        [human.labels[i] for i in indices] + ai.labels,
        ["human"] * len(indices) + ["ai"] * len(ai),
    )


class ProbabilityTable:
    classes_ = CATEGORIES

    def __init__(self, probabilities):
        self.probabilities = probabilities

    def predict_proba(self, texts):
        if len(texts) != len(self.probabilities):
            raise ValueError("Probability row count mismatch")
        return self.probabilities


def metrics(gold, predicted, probabilities=None):
    benign = {"personal", "otp", "service", "transaction"}
    risk = {"marketing", "suspicious"}
    certain = [i for i, label in enumerate(gold) if label != "uncertain"]
    result = {
        "samples": len(gold), "accuracy": float(accuracy_score(gold, predicted)),
        "macro_f1": float(f1_score(gold, predicted, labels=CATEGORIES, average="macro", zero_division=0)),
        "classification_report": classification_report(gold, predicted, labels=CATEGORIES, output_dict=True, zero_division=0),
        "confusion_matrix_labels": CATEGORIES,
        "confusion_matrix": confusion_matrix(gold, predicted, labels=CATEGORIES).tolist(),
        "six_certain_class_accuracy": float(accuracy_score([gold[i] for i in certain], [predicted[i] for i in certain])),
        "category_risk_ham_fpr": sum(y in benign and p in risk for y, p in zip(gold, predicted)) / max(1, sum(y in benign for y in gold)),
        "category_risk_recall": sum(y in risk and p in risk for y, p in zip(gold, predicted)) / max(1, sum(y in risk for y in gold)),
        "predicted_uncertain": predicted.count("uncertain"),
    }
    if probabilities is not None:
        scored = evaluate(ProbabilityTable(probabilities), [""] * len(gold), gold, category_decision="argmax")
        result["thresholded_risk"] = {key: scored[key] for key in (
            "threshold", "risk_false_positive_rate", "risk_recall", "important_category_false_positive_rate")}
    return result


def config_key(config):
    return json.dumps(config, sort_keys=True)


def merge_validation_scores(reports):
    merged = {}
    for rows in reports:
        for row in rows:
            if any(not np.isfinite(row[k]) or not 0 <= row[k] <= 1 for k in ("accuracy", "macro_f1")):
                raise ValueError("Invalid cached validation score")
            key = config_key(row["config"])
            if key in merged and any(abs(merged[key][k] - row[k]) > 1e-12 for k in ("accuracy", "macro_f1")):
                raise ValueError("Conflicting cached validation scores")
            merged[key] = row
    return merged


def select_config(human, ai, indices, candidates, *, seed: int, folds: int, cached_scores=None):
    # Vectorization is fitted within each inner training fold, never on its
    # validation texts. Reuse the matrix only across supervised hyperparameters.
    predictions = [[] for _ in candidates]
    gold = []
    cached_scores = cached_scores or {}
    missing = [c for c in candidates if config_key(asdict(c)) not in cached_scores]
    for inner_train, inner_val in (grouped_folds(human, indices, folds, seed) if missing else []):
        texts, labels, sources = training_rows(human, ai, inner_train)
        gold.extend(human.labels[i] for i in inner_val)
        for ngrams in sorted({(c.ngram_min, c.ngram_max) for c in missing}):
            vectorizer = make_vectorizer(SparseConfig(ngram_min=ngrams[0], ngram_max=ngrams[1]))
            matrix = vectorizer.fit_transform(normalize_sparse_texts(texts))
            held = vectorizer.transform(normalize_sparse_texts([human.texts[i] for i in inner_val]))
            for n, config in enumerate(candidates):
                if (config.ngram_min, config.ngram_max) != ngrams:
                    continue
                if config_key(asdict(config)) in cached_scores:
                    continue
                model = fit_classifier(matrix, labels, sources, config, seed=seed)
                predictions[n].extend(model.predict(held).tolist())
        print(json.dumps({"selection_seed": seed, "validation_rows_scored": len(gold)}, ensure_ascii=False), flush=True)
    scores = [cached_scores[config_key(asdict(c))] if config_key(asdict(c)) in cached_scores else
              {"config": asdict(c), "accuracy": float(accuracy_score(gold, p)),
               "macro_f1": float(f1_score(gold, p, labels=CATEGORIES, average="macro", zero_division=0))}
              for c, p in zip(candidates, predictions)]
    # Deterministic preference for stronger regularization on exact metric ties.
    selected = max(range(len(candidates)), key=lambda i: (
        scores[i]["accuracy"], scores[i]["macro_f1"], -candidates[i].c,
        candidates[i].classifier == "logistic", -abs(candidates[i].ai_weight - 0.3), -candidates[i].uncertain_weight))
    return candidates[selected], scores


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--human", type=Path, default=ROOT / "data/processed/opencode-free-synthetic-20261017-human-reviewed.jsonl")
    parser.add_argument("--ai", type=Path, action="append", help="Training-only weak labels; repeat for additional local sources")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/experimental/seven-class-optimized-20261019")
    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument("--inner-folds", type=int, default=3)
    parser.add_argument("--threads", type=int, default=1)
    parser.add_argument("--seed", type=int, default=20261019)
    parser.add_argument("--uncertain-weights", type=float, nargs="+", default=[0.25, 1.0])
    parser.add_argument("--classifiers", nargs="+", choices=["logistic", "svm", "complement_nb", "multinomial_nb"], default=["logistic", "svm"])
    parser.add_argument("--c-values", type=float, nargs="+", default=[1.0, 4.0, 16.0],
                        help="Inverse regularization for linear models; smoothing alpha for NB models")
    parser.add_argument("--reuse-search-report", type=Path, action="append", default=[],
                        help="Reuse inner validation scores from local runs with identical data and folds; never reuse outer scores for selection")
    args = parser.parse_args()
    if args.folds < 2 or args.inner_folds < 2 or args.threads < 1:
        parser.error("fold counts must be >=2; threads must be positive")
    if not args.uncertain_weights or any(not np.isfinite(w) or not 0 < w <= 1 for w in args.uncertain_weights):
        parser.error("uncertain weights must be finite values in (0, 1]")
    if not args.c_values or any(not np.isfinite(c) or c <= 0 for c in args.c_values):
        parser.error("C/alpha values must be positive and finite")
    if args.output.exists():
        parser.error("Output already exists; use a new directory")
    ai_paths = args.ai or [ROOT / "data/processed/opencode-free-synthetic-20261017-all-labeled.jsonl"]
    human, ai, data_report = prepare_corpora(args.human, ai_paths)
    cached_reports = [json.loads(p.read_text(encoding="utf-8")) for p in args.reuse_search_report]
    for report in cached_reports:
        if report["data"] != data_report or any(report["protocol"][k] != value for k, value in (
            ("seed", args.seed), ("folds", args.folds), ("inner_folds", args.inner_folds), ("category_decision", "argmax")
        )) or report["experiment"] != "seven-class-source-balanced-nested-template-cv":
            raise ValueError("Cached search data or evaluation protocol does not match")
    args.output.mkdir(parents=True, mode=0o700)
    os.chmod(args.output, 0o700)
    candidates = [SparseConfig(a, b, classifier, c, weight, uncertain_weight)
                  for a, b in [(1, 4), (2, 5)] for classifier in args.classifiers
                  for c in args.c_values for weight in [0.1, 0.3, 1.0]
                  for uncertain_weight in args.uncertain_weights]
    gold, predicted, probabilities, fold_reports = [], [], [], []
    all_indices = list(range(len(human)))
    start = time.perf_counter()
    with threadpool_limits(limits=args.threads):
        for fold, (train, heldout) in enumerate(grouped_folds(human, all_indices, args.folds, args.seed)):
            for report in cached_reports:
                expected_ids = [human.template_ids[i] for i in heldout]
                if report["folds"][fold]["test_template_ids"] != expected_ids:
                    raise ValueError("Cached search outer fold templates do not match")
            cached_scores = merge_validation_scores([r["folds"][fold]["selection"] for r in cached_reports])
            config, search = select_config(human, ai, train, candidates, seed=args.seed + fold + 1000, folds=args.inner_folds, cached_scores=cached_scores)
            model = fit_sparse_model(*training_rows(human, ai, train), config, seed=args.seed + fold)
            probs = model.predict_proba([human.texts[i] for i in heldout])
            fold_pred = [model.classes_[i] for i in np.argmax(probs, axis=1)]
            fold_gold = [human.labels[i] for i in heldout]
            gold.extend(fold_gold)
            predicted.extend(fold_pred)
            probabilities.extend(probs.tolist())
            result = metrics(fold_gold, fold_pred, probs)
            fold_reports.append({"fold": fold, "config": asdict(config), "selection": search,
                                 "test_template_ids": [human.template_ids[i] for i in heldout],
                                 "train_template_ids": sorted(set(human.template_ids[i] for i in train) | set(ai.template_ids)),
                                 "metrics": result, "gold": fold_gold, "predicted": fold_pred})
            private_json(args.output / f"fold-{fold}.json", fold_reports[-1])
            print(json.dumps({"fold": fold, "selected": asdict(config), "accuracy": result["accuracy"],
                              "elapsed_seconds": round(time.perf_counter() - start)}, ensure_ascii=False), flush=True)
        # Deployment configuration is selected afresh by inner CV over all
        # human labels; outer test scores do not select hyperparameters.
        config, selection = select_config(human, ai, all_indices, candidates, seed=args.seed + 10000, folds=args.inner_folds,
                                          cached_scores=merge_validation_scores([r["final_selection"] for r in cached_reports]))
        model = fit_sparse_model(*training_rows(human, ai, all_indices), config, seed=args.seed)
        version_hash = hashlib.sha256(json.dumps(
            {"config": asdict(config), "sources": data_report["source_sha256"], "seed": args.seed},
            sort_keys=True).encode("utf-8")).hexdigest()[:10]
        bundle = {
            "model": model, "classes": model.classes_, "version": f"seven-class-sparse-20261019-{version_hash}",
            "category_decision": "argmax", "decision_threshold": 0.5,
            "review_confidence_threshold": 0.6, "confidence_calibrated": False,
            "always_requires_review": True, "config": asdict(config),
        }
        artifact = args.output / "model.joblib"
        with artifact.open("xb") as handle:
            os.chmod(artifact, 0o600)
            joblib.dump(bundle, handle, compress=3)
    report = {
        "experiment": "seven-class-source-balanced-nested-template-cv", "data": data_report,
        "reused_inner_search_reports": {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in args.reuse_search_report},
        "evaluation_support": {"human_by_class": dict(Counter(human.labels)),
                               "template_groups": len(set(human.template_ids)),
                               "synthetic_rows": sum(human.synthetic_flags),
                               "natural_rows": sum(not flag for flag in human.synthetic_flags)},
        "protocol": {"folds": args.folds, "inner_folds": args.inner_folds, "seed": args.seed,
                     "selection": "inner human-label accuracy, then seven-class macro F1; outer labels excluded",
                     "ai_training_only": True, "cross_source_templates_isolated": True,
                     "outer_training_refit_includes_inner_validation": True,
                     "category_decision": "argmax", "natural_sms_evaluation_rows": sum(not flag for flag in human.synthetic_flags)},
        "aggregate": metrics(gold, predicted, probabilities), "folds": fold_reports,
        "final_config": asdict(config), "final_selection": selection,
        "model_version": bundle["version"],
        "artifact_sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
        "elapsed_seconds": time.perf_counter() - start, "promotion_eligible": False,
        "limitations": ["Cross-validation on the supplied corpus does not replace an independent natural-SMS test set.",
                        f"Human uncertain labels: {human.labels.count('uncertain')}; inspect class support before interpreting seventh-class recall.",
                        "Scores are uncalibrated. All predictions require review.",
                        "Prior experiments reused this corpus; nested CV remains exploratory evidence."],
    }
    private_json(args.output / "evaluation.json", report)
    print(json.dumps({"output": str(args.output), "config": asdict(config), "aggregate": report["aggregate"]}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
