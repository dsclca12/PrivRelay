import pytest

from privatesms.evaluation import choose_threshold, evaluate
from privatesms.inference import predict
from privatesms.datasets import prepare_dataset
from privatesms.training import train_baseline


class CategoryModel:
    classes_ = ["personal", "otp", "service", "transaction", "marketing", "suspicious", "uncertain"]

    def predict_proba(self, texts):
        rows = [
            [0.80, 0.05, 0.05, 0.02, 0.02, 0.01, 0.05],
            [0.02, 0.02, 0.02, 0.02, 0.78, 0.10, 0.04],
            [0.02, 0.02, 0.03, 0.02, 0.10, 0.78, 0.03],
            [0.05, 0.05, 0.05, 0.05, 0.10, 0.10, 0.60],
        ]
        mapping = {"suspected phishing": rows[2], "ambiguous": rows[3]}
        return [mapping.get(text, rows[index % len(rows)]) for index, text in enumerate(texts)]


def test_multiclass_risk_score_and_review_policy():
    model = CategoryModel()
    texts = ["a", "b", "c", "d"]
    labels = ["personal", "marketing", "suspicious", "uncertain"]
    threshold = choose_threshold(model, texts, labels, ham_fpr_limit=0.34)
    assert threshold["target_met"]
    report = evaluate(model, texts, labels, threshold=0.5)
    assert report["macro_f1"] == 1.0
    assert report["important_category_false_positive_rate"]["personal"] == 0
    assert report["risk_false_positive_rate"] == 0
    assert "uncertain" in report["per_class"]
    bundle = {"model": model, "classes": model.classes_, "version": "test-multiclass-v1", "decision_threshold": 0.5}
    suspicious = predict(bundle, "suspected phishing")
    assert suspicious["category"] == "suspicious"
    assert suspicious["is_spam"] is True
    assert predict(bundle, "ambiguous")["needs_review"] is True


def test_multiclass_risk_threshold_selects_a_consistent_category():
    class BorderlineModel:
        classes_ = CategoryModel.classes_

        def predict_proba(self, texts):
            return [
                [0.01, 0.96, 0.01, 0.005, 0.005, 0.005, 0.005]
                if text == "benign" else [0.02, 0.03, 0.35, 0.05, 0.28, 0.12, 0.15]
                for text in texts
            ]

    bundle = {"model": BorderlineModel(), "classes": CategoryModel.classes_, "version": "test-v1"}
    risky = predict(bundle, "message", threshold=0.3)
    assert risky["is_spam"] is True
    assert risky["category"] == "marketing"
    report = evaluate(BorderlineModel(), ["message", "benign"], ["marketing", "otp"], threshold=0.3)
    assert report["accuracy"] == 1.0
    assert report["risk_false_positive_rate"] == 0.0
    benign = predict(bundle, "message", threshold=0.45)
    assert benign["is_spam"] is False
    assert benign["category"] == "service"


def test_seven_category_linear_baseline_trains(tmp_path):
    categories = CategoryModel.classes_
    rows = []
    for label_index, category in enumerate(categories):
        for sample_index in range(8):
            suffix = chr(0x4e00 + sample_index)
            rows.append((f"类别{category}短信场景{chr(0x4e00 + label_index)}样例{suffix}", category))
    dataset, _ = prepare_dataset(rows)
    model, splits = train_baseline(dataset, model_path=tmp_path / "multi.joblib")
    assert set(model.classes_) == set(categories)
    assert all(splits[name] for name in ("train", "validation", "test"))
    assert model.predict_proba([dataset.texts[splits["test"][0]]])[0].sum() == pytest.approx(1.0)
