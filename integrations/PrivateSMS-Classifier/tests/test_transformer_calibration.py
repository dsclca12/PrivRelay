import pytest

from privatesms.training.transformer import _fit_temperature


def test_temperature_scaling_fits_on_supported_validation_classes():
    probabilities = []
    labels = []
    for _ in range(8):
        probabilities.append([0.9, 0.1])
        labels.append("ham")
        probabilities.append([0.1, 0.9])
        labels.append("spam")
    for _ in range(2):
        probabilities.append([0.9, 0.1])
        labels.append("spam")
        probabilities.append([0.1, 0.9])
        labels.append("ham")

    result = _fit_temperature(probabilities, labels, ["ham", "spam"])

    assert result["confidence_calibrated"] is True
    assert result["method"] == "temperature_scaling"
    assert result["temperature"] > 1.0
    assert result["validation_nll_after"] < result["validation_nll_before"]
    assert result["validation_class_support"] == {"ham": 10, "spam": 10}


def test_temperature_scaling_stays_disabled_without_minimum_class_support():
    result = _fit_temperature(
        [[0.9, 0.1]] * 4 + [[0.1, 0.9]] * 10,
        ["ham"] * 4 + ["spam"] * 10,
        ["ham", "spam"],
    )

    assert result["confidence_calibrated"] is False
    assert result["temperature"] == 1.0
    assert result["reason"] == "insufficient_validation_support"


def test_temperature_scaling_stays_disabled_when_validation_nll_does_not_improve():
    result = _fit_temperature(
        [[0.5, 0.5]] * 20,
        ["ham"] * 10 + ["spam"] * 10,
        ["ham", "spam"],
    )

    assert result["confidence_calibrated"] is False
    assert result["temperature"] == 1.0
    assert result["reason"] == "temperature_fit_no_improvement"


@pytest.mark.parametrize("probabilities", [[], [[0.8, 0.1]], [[0.8, float("nan")]]])
def test_temperature_scaling_rejects_invalid_probability_matrices(probabilities):
    with pytest.raises(ValueError, match="calibration probabilities"):
        _fit_temperature(probabilities, ["ham", "spam"], ["ham", "spam"])
