import pytest

from privatesms.evaluation import choose_threshold, evaluate


class DummyModel:
    classes_ = ["ham", "spam"]

    def predict_proba(self, texts):
        return [[1 - score, score] for score in [0.01, 0.2, 0.7, 0.95][:len(texts)]]


def test_metrics_report_fpr_and_threshold():
    model = DummyModel()
    texts = ["a", "b", "c", "d"]
    labels = ["ham", "ham", "spam", "spam"]
    selected = choose_threshold(model, texts, labels, ham_fpr_limit=0)
    assert selected["target_met"] is True
    result = evaluate(model, texts, labels, threshold=selected["threshold"])
    assert result["ham_false_positive_rate"] == 0
    assert result["confusion_matrix_labels"] == ["ham", "spam"]
    assert "macro_f1" in result
    assert result["probability_calibration"]["bins"] == 10
    assert result["probability_calibration"]["brier_score"] >= 0
    assert result["probability_calibration"]["top_label_ece"] >= 0


def test_threshold_arguments_must_be_probabilities():
    model = DummyModel()
    with pytest.raises(ValueError, match="ham_fpr_limit"):
        choose_threshold(model, ["a", "b"], ["ham", "spam"], ham_fpr_limit=1.1)
    with pytest.raises(ValueError, match="threshold"):
        evaluate(model, ["a", "b"], ["ham", "spam"], threshold=-0.1)
