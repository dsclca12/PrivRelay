import json

import pytest
import joblib
from fastapi.testclient import TestClient

from privatesms.api.app import create_app
from privatesms.inference.registry import ModelRegistry, artifact_sha256


class RegistryBinaryModel:
    classes_ = ["ham", "spam"]

    def predict_proba(self, texts):
        return [[0.99, 0.01] for _ in texts]


def _evaluation(path, *, fpr, important=None, training_only=0, synthetic=0, template_overlap=0, include_isolation=True, risk_recall=0.5, per_class_support=None, classes=None, candidate=None, calibration_ece=0.05):
    classes = classes or ["ham", "spam"]
    per_class_support = per_class_support or {"ham": 50, "spam": 50}
    report = {
        "test_data_policy": {"training_only_rows": training_only, "synthetic_rows": synthetic, "samples": 100},
        "template_split_isolation": {
            "template_groups": {"train": 70, "validation": 15, "test": 15},
            "overlap_groups": {
                "train_validation": template_overlap,
                "train_test": 0,
                "validation_test": 0,
            },
            "disjoint": template_overlap == 0,
        },
        "model_classes": classes,
        "test": {
            "samples": 100,
            "risk_false_positive_rate": fpr,
            "risk_recall": risk_recall,
            "important_category_false_positive_rate": important or {"ham": fpr},
            "per_class": {label: {"support": count} for label, count in per_class_support.items()},
            "probability_calibration": {"brier_score": 0.1, "top_label_ece": calibration_ece, "bins": 10},
        },
    }
    if set(classes) == {"personal", "otp", "service", "transaction", "marketing", "suspicious", "uncertain"}:
        report["confidence_calibration"] = {
            "method": "temperature_scaling",
            "confidence_calibrated": True,
        }
    if not include_isolation:
        report.pop("template_split_isolation")
    if candidate is not None:
        report["candidate_artifact_sha256"] = artifact_sha256(candidate)
    path.write_text(json.dumps(report), encoding="utf-8")


def test_registry_requires_test_gate_and_rolls_back_atomically(tmp_path):
    root = tmp_path / "registry"
    model1 = tmp_path / "model-v1.joblib"
    model2 = tmp_path / "model-v2.joblib"
    model1.write_bytes(b"first local artifact")
    model2.write_bytes(b"second local artifact")
    evaluation = tmp_path / "evaluation.json"
    registry = ModelRegistry(root)
    registry.register(model1, "v1")
    registry.register(model2, "v2")
    _evaluation(evaluation, fpr=0.02)
    with pytest.raises(ValueError, match="FPR gate"):
        registry.activate("v1", evaluation_report=evaluation)
    _evaluation(evaluation, fpr=0.005, training_only=1)
    with pytest.raises(ValueError, match="non-synthetic"):
        registry.activate("v1", evaluation_report=evaluation)
    _evaluation(evaluation, fpr=0.005, template_overlap=1)
    with pytest.raises(ValueError, match="template-group isolation"):
        registry.activate("v1", evaluation_report=evaluation)
    _evaluation(evaluation, fpr=0.005, include_isolation=False)
    with pytest.raises(ValueError, match="template-group isolation"):
        registry.activate("v1", evaluation_report=evaluation)
    _evaluation(evaluation, fpr=0.005, candidate=model1)
    registry.activate("v1", evaluation_report=evaluation)
    with pytest.raises(ValueError, match="fingerprint"):
        registry.activate("v2", evaluation_report=evaluation)
    _evaluation(evaluation, fpr=0.005, candidate=model2)
    registry.activate("v2", evaluation_report=evaluation)
    assert registry.current()["active_version"] == "v2"
    assert registry.current()["previous_version"] == "v1"
    assert root.stat().st_mode & 0o777 == 0o700
    assert (root / "versions").stat().st_mode & 0o777 == 0o700
    assert (root / "versions/v1").stat().st_mode & 0o777 == 0o700
    assert (root / "versions/v1/model-v1.joblib").stat().st_mode & 0o777 == 0o600
    assert (root / "versions/v1/manifest.json").stat().st_mode & 0o777 == 0o600
    assert (root / "active.json").stat().st_mode & 0o777 == 0o600
    assert registry.rollback().name == "model-v1.joblib"
    assert registry.current()["active_version"] == "v1"


def test_registry_detects_artifact_tampering(tmp_path):
    candidate = tmp_path / "candidate.joblib"
    candidate.write_text("trusted", encoding="utf-8")
    evaluation = tmp_path / "evaluation.json"
    _evaluation(evaluation, fpr=0.0)
    registry = ModelRegistry(tmp_path / "registry")
    registry.register(candidate, "release-1")
    pointer = tmp_path / "registry/versions/release-1/candidate.joblib"
    pointer.write_text("tampered", encoding="utf-8")
    with pytest.raises(ValueError, match="integrity"):
        registry.activate("release-1", evaluation_report=evaluation)


def test_directory_fingerprint_ignores_training_checkpoint_and_rejects_symlinks(tmp_path):
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    (candidate / "model.bin").write_bytes(b"model")
    before = artifact_sha256(candidate)
    (candidate / "training-checkpoint.pt").write_bytes(b"large, non-deployment checkpoint")
    (candidate / "scratch.tmp").write_bytes(b"temporary")
    hidden = candidate / ".cache.staging"
    hidden.mkdir()
    (hidden / "checkpoint.bin").write_bytes(b"staged temporary content")
    assert artifact_sha256(candidate) == before

    (candidate / "external-link").symlink_to(tmp_path / "outside")
    with pytest.raises(ValueError, match="symlinks"):
        artifact_sha256(candidate)


def test_registry_rejects_invalid_or_incomplete_risk_evaluation(tmp_path):
    candidate = tmp_path / "candidate.joblib"
    candidate.write_text("artifact", encoding="utf-8")
    registry = ModelRegistry(tmp_path / "registry")
    registry.register(candidate, "candidate")
    evaluation = tmp_path / "evaluation.json"

    _evaluation(evaluation, fpr=float("nan"))
    with pytest.raises(ValueError, match="risk FPR"):
        registry.activate("candidate", evaluation_report=evaluation)
    _evaluation(evaluation, fpr=0.0, risk_recall=None)
    with pytest.raises(ValueError, match="risk recall"):
        registry.activate("candidate", evaluation_report=evaluation)
    _evaluation(evaluation, fpr=0.0, per_class_support={"ham": 100, "spam": 0})
    with pytest.raises(ValueError, match="positive support"):
        registry.activate("candidate", evaluation_report=evaluation)
    _evaluation(evaluation, fpr=0.0, per_class_support={"ham": 98, "spam": 1})
    with pytest.raises(ValueError, match="support does not match"):
        registry.activate("candidate", evaluation_report=evaluation)


def test_registry_requires_all_seven_classes_for_business_model(tmp_path):
    candidate = tmp_path / "candidate.joblib"
    candidate.write_text("artifact", encoding="utf-8")
    registry = ModelRegistry(tmp_path / "registry")
    registry.register(candidate, "candidate")
    evaluation = tmp_path / "evaluation.json"
    _evaluation(evaluation, fpr=0.0, classes=["personal", "otp", "service", "transaction", "marketing", "suspicious"])

    with pytest.raises(ValueError, match="complete seven-class schema"):
        registry.activate("candidate", evaluation_report=evaluation)


def test_registry_accepts_complete_seven_class_test_evidence(tmp_path):
    candidate = tmp_path / "candidate.joblib"
    candidate.write_text("artifact", encoding="utf-8")
    registry = ModelRegistry(tmp_path / "registry")
    registry.register(candidate, "seven-class")
    evaluation = tmp_path / "evaluation.json"
    classes = ["personal", "otp", "service", "transaction", "marketing", "suspicious", "uncertain"]
    supports = {"personal": 10, "otp": 10, "service": 10, "transaction": 10, "marketing": 20, "suspicious": 20, "uncertain": 20}
    important = {"personal": 0.0, "otp": 0.0, "service": 0.0, "transaction": 0.0}
    _evaluation(evaluation, fpr=0.0, classes=classes, per_class_support=supports, important=important, candidate=candidate)

    assert registry.activate("seven-class", evaluation_report=evaluation).is_file()


def test_registry_rejects_poorly_calibrated_seven_class_test_predictions(tmp_path):
    candidate = tmp_path / "candidate.joblib"
    candidate.write_text("artifact", encoding="utf-8")
    registry = ModelRegistry(tmp_path / "registry")
    registry.register(candidate, "seven-class")
    evaluation = tmp_path / "evaluation.json"
    classes = ["personal", "otp", "service", "transaction", "marketing", "suspicious", "uncertain"]
    supports = {label: 10 for label in classes}
    important = {"personal": 0.0, "otp": 0.0, "service": 0.0, "transaction": 0.0}
    _evaluation(evaluation, fpr=0.0, classes=classes, per_class_support=supports, important=important, candidate=candidate, calibration_ece=0.11)

    with pytest.raises(ValueError, match="top-label ECE"):
        registry.activate("seven-class", evaluation_report=evaluation)


def test_registry_resolves_from_read_only_mount(tmp_path):
    candidate = tmp_path / "candidate.joblib"
    candidate.write_bytes(b"local artifact")
    evaluation = tmp_path / "evaluation.json"
    _evaluation(evaluation, fpr=0.0, candidate=candidate)
    registry = ModelRegistry(tmp_path / "registry")
    registry.register(candidate, "read-only")
    registry.activate("read-only", evaluation_report=evaluation)

    for path in sorted(registry.root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        path.chmod(0o500 if path.is_dir() else 0o400)
    registry.root.chmod(0o500)

    assert registry.current()["active_version"] == "read-only"
    assert registry.resolve().read_bytes() == b"local artifact"


def test_api_resolves_active_registered_model(tmp_path, monkeypatch):
    candidate = tmp_path / "candidate.joblib"
    joblib.dump({"model": RegistryBinaryModel(), "classes": ["ham", "spam"], "version": "registry-v1", "decision_threshold": 0.5}, candidate)
    evaluation = tmp_path / "evaluation.json"
    _evaluation(evaluation, fpr=0.0, candidate=candidate)
    registry_path = tmp_path / "versions"
    registry = ModelRegistry(registry_path)
    registry.register(candidate, "v1")
    registry.activate("v1", evaluation_report=evaluation)
    monkeypatch.delenv("PRIVATESMS_MODEL_PATH", raising=False)
    monkeypatch.setenv("PRIVATESMS_MODEL_REGISTRY", str(registry_path))
    with TestClient(create_app(feedback_db_path=tmp_path / "feedback.sqlite3")) as client:
        assert client.get("/healthz").json()["model_version"] == "v1"
        result = client.post("/api/v1/classify", json={"text": "虚构通知"}).json()
        assert result["model_version"] == "v1"
