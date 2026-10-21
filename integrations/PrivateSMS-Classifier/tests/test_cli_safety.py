import pytest

from privatesms.cli import _ensure_report_outside_artifact


def test_evaluation_report_cannot_overwrite_model_file(tmp_path):
    model = tmp_path / "model.joblib"
    model.write_text("model", encoding="utf-8")

    with pytest.raises(ValueError, match="cannot overwrite"):
        _ensure_report_outside_artifact(model, model)


def test_evaluation_report_must_be_outside_model_directory(tmp_path):
    model_dir = tmp_path / "model"
    model_dir.mkdir()

    with pytest.raises(ValueError, match="outside"):
        _ensure_report_outside_artifact(model_dir / "evaluation.json", model_dir)


def test_evaluation_report_may_be_next_to_model_artifact(tmp_path):
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    report = tmp_path / "evaluation.json"

    _ensure_report_outside_artifact(report, model_dir)
