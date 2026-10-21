import joblib
import pytest
from fastapi.testclient import TestClient

from privatesms.api.app import create_app


class BinaryModel:
    classes_ = ["ham", "spam"]

    def predict_proba(self, texts):
        return [[0.96, 0.04] for _ in texts]


class MulticlassModel:
    classes_ = ["personal", "otp", "service", "transaction", "marketing", "suspicious", "uncertain"]

    def predict_proba(self, texts):
        return [[0.01, 0.96, 0.01, 0.005, 0.005, 0.005, 0.005] for _ in texts]


class SuspiciousModel:
    classes_ = ["personal", "otp", "service", "transaction", "marketing", "suspicious", "uncertain"]

    def predict_proba(self, texts):
        return [[0.005, 0.005, 0.005, 0.005, 0.01, 0.96, 0.005] for _ in texts]


class UncalibratedSuspiciousModel(SuspiciousModel):
    def predict_proba(self, texts):
        return [[0.005, 0.005, 0.005, 0.005, 0.005, 0.97, 0.005] for _ in texts]


def _sms_score_payload(**overrides):
    return {
        "address": "10690000000",
        "body": "虚构的风控评估短信，勿实际发送",
        "timestamp": 1774576609886,
        "localScore": 0.81,
        "threshold": 0.82,
        "profile": "balanced",
        "modelVersion": "ultrahub-local-v1",
        **overrides,
    }


def test_classify_api_auth_and_binary_caution(tmp_path):
    model_path = tmp_path / "model.joblib"
    joblib.dump({"model": BinaryModel(), "classes": ["ham", "spam"], "version": "test-v1", "decision_threshold": 0.5, "confidence_calibrated": True}, model_path)
    app = create_app(model_path=model_path, api_key="local-secret", feedback_db_path=tmp_path / "feedback.sqlite3")
    with TestClient(app) as client:
        assert client.get("/healthz").json() == {"status": "ok", "model_version": "test-v1"}
        unauthorized = client.post("/api/v1/classify", json={"text": "test"})
        assert unauthorized.status_code == 401
        response = client.post("/api/v1/classify", headers={"X-API-Key": "local-secret"}, json={"text": "test", "sender": "10600000000"})
        assert response.status_code == 200
        result = response.json()
        assert result["category"] == "uncertain"
        assert result["needs_review"] is True
        assert result["confidence_calibrated"] is False
        assert "sender" not in result
        assert client.post("/sms/score", json=_sms_score_payload()).status_code == 401
        server_result = client.post("/sms/score", headers={"X-API-Key": "local-secret"}, json=_sms_score_payload())
        assert server_result.status_code == 200
        assert server_result.json()["action"] == "allow"
        assert server_result.json()["reason"] == "review_required:uncertain"


def test_sms_score_compat_route_blocks_only_calibrated_confident_risk(tmp_path):
    model_path = tmp_path / "suspicious.joblib"
    joblib.dump({
        "model": SuspiciousModel(),
        "classes": SuspiciousModel.classes_,
        "version": "seven-class-test",
        "decision_threshold": 0.5,
        "confidence_calibrated": True,
    }, model_path)
    app = create_app(model_path=model_path, feedback_db_path=tmp_path / "feedback.sqlite3")

    with TestClient(app) as client:
        response = client.post("/sms/score", json=_sms_score_payload())

    assert response.status_code == 200
    result = response.json()
    assert result["action"] == "block"
    assert result["category"] == "suspicious"
    assert result["reason"] == "risk_category:suspicious"
    assert result["modelVersion"] == "seven-class-test"
    assert result["thresholdUsed"] == 0.5


def test_sms_score_validation_never_echoes_message(tmp_path):
    model_path = tmp_path / "binary.joblib"
    joblib.dump({"model": BinaryModel(), "classes": BinaryModel.classes_, "version": "test-v1"}, model_path)
    sentinel = "SMS_BODY_MUST_NOT_BE_ECHOED"
    with TestClient(create_app(model_path=model_path, feedback_db_path=tmp_path / "feedback.sqlite3")) as client:
        response = client.post("/sms/score", json=_sms_score_payload(body=sentinel + ("x" * 4096)))
    assert response.status_code == 422
    assert sentinel not in response.text


def test_sms_score_never_blocks_uncalibrated_seven_class_predictions(tmp_path):
    model_path = tmp_path / "uncalibrated.joblib"
    joblib.dump({
        "model": UncalibratedSuspiciousModel(),
        "classes": UncalibratedSuspiciousModel.classes_,
        "version": "uncalibrated-test",
        "decision_threshold": 0.5,
        "confidence_calibrated": False,
    }, model_path)
    with TestClient(create_app(model_path=model_path, feedback_db_path=tmp_path / "feedback.sqlite3")) as client:
        result = client.post("/sms/score", json=_sms_score_payload()).json()
    assert result["category"] == "suspicious"
    assert result["action"] == "allow"
    assert result["reason"] == "uncalibrated_category_allow"


def test_api_reports_registry_version_for_health_and_classify(tmp_path, monkeypatch):
    registry = tmp_path / "registry"
    model_path = registry / "versions" / "baseline-calibrated-test" / "model.joblib"
    model_path.parent.mkdir(parents=True)
    joblib.dump({"model": BinaryModel(), "classes": ["ham", "spam"], "version": "baseline-char-tfidf-lr-v1"}, model_path)
    monkeypatch.setenv("PRIVATESMS_MODEL_REGISTRY", str(registry))
    app = create_app(model_path=model_path, feedback_db_path=tmp_path / "feedback.sqlite3")

    with TestClient(app) as client:
        assert client.get("/healthz").json()["model_version"] == "baseline-calibrated-test"
        result = client.post("/api/v1/classify", json={"text": "虚构短信样例"}).json()
        assert result["model_version"] == "baseline-calibrated-test"


def test_feedback_requires_auth_and_explicit_human_review(tmp_path):
    model_path = tmp_path / "model.joblib"
    joblib.dump({"model": BinaryModel(), "classes": ["ham", "spam"], "version": "test-v1"}, model_path)
    app = create_app(model_path=model_path, api_key="local-secret", feedback_db_path=tmp_path / "feedback.sqlite3")
    with TestClient(app) as client:
        payload = {
            "text": "这是一条本地纠错样例短信",
            "feedback_type": "false_spam",
            "predicted_category": "marketing",
            "corrected_category": "otp",
            "model_version": "test-v1",
        }
        assert client.post("/api/v1/feedback", json=payload).status_code == 401
        headers = {"X-API-Key": "local-secret"}
        created = client.post("/api/v1/feedback", headers=headers, json=payload)
        assert created.status_code == 202
        feedback_id = created.json()["feedback_id"]
        pending = client.get("/api/v1/feedback/pending", headers=headers).json()["items"]
        assert len(pending) == 1 and pending[0]["text"] == payload["text"]
        missing_category = client.post(f"/api/v1/feedback/{feedback_id}/review", headers=headers, json={"decision": "approve"})
        assert missing_category.status_code == 422
        approved = client.post(f"/api/v1/feedback/{feedback_id}/review", headers=headers, json={"decision": "approve", "category": "otp"})
        assert approved.status_code == 200

        from privatesms.feedback import FeedbackStore
        from privatesms.datasets import load_dataset
        import json
        export_path = tmp_path / "approved.jsonl"
        assert FeedbackStore(tmp_path / "feedback.sqlite3").export_approved(export_path) == 1
        assert (tmp_path / "feedback.sqlite3").stat().st_mode & 0o777 == 0o600
        assert export_path.stat().st_mode & 0o777 == 0o600
        row = json.loads(export_path.read_text(encoding="utf-8"))
        assert row["human_verified"] is True and row["source"] == "human" and row["label"] == "otp"
        excluded, _ = load_dataset(export_path)
        approved_for_training, report = load_dataset(export_path, include_feedback=True)
        assert len(excluded) == 0
        assert len(approved_for_training) == 1 and approved_for_training.training_only == [True]
        assert report.included_training_only_rows == 1


def test_feedback_routes_are_disabled_until_api_key_is_configured(tmp_path, monkeypatch):
    model_path = tmp_path / "model.joblib"
    joblib.dump({"model": BinaryModel(), "classes": ["ham", "spam"], "version": "test-v1"}, model_path)
    monkeypatch.delenv("PRIVATESMS_API_KEY", raising=False)
    app = create_app(model_path=model_path, feedback_db_path=tmp_path / "feedback.sqlite3")
    payload = {
        "text": "本地反馈样例短信",
        "feedback_type": "wrong_category",
        "predicted_category": "service",
        "corrected_category": "personal",
        "model_version": "test-v1",
    }
    with TestClient(app) as client:
        assert client.post("/api/v1/feedback", json=payload).status_code == 503
        assert client.get("/api/v1/feedback/pending").status_code == 503
        assert client.post(
            "/api/v1/feedback/any-id/review",
            json={"decision": "reject"},
        ).status_code == 503


def test_request_rejects_extra_fields(tmp_path):
    model_path = tmp_path / "model.joblib"
    joblib.dump({"model": BinaryModel(), "classes": ["ham", "spam"], "version": "test-v1"}, model_path)
    with TestClient(create_app(model_path=model_path)) as client:
        response = client.post("/api/v1/classify", json={"text": "test", "raw_sms": "should not be echoed"})
        assert response.status_code == 422
        assert "should not be echoed" not in response.text


def test_validation_errors_never_echo_sms_text(tmp_path):
    model_path = tmp_path / "model.joblib"
    joblib.dump({"model": BinaryModel(), "classes": ["ham", "spam"], "version": "test-v1"}, model_path)
    sentinel = "PRIVATE_SMS_SENTINEL"
    with TestClient(create_app(model_path=model_path, feedback_db_path=tmp_path / "feedback.sqlite3")) as client:
        too_long = client.post("/api/v1/classify", json={"text": sentinel + ("x" * 4096)})
        extra_field = client.post("/api/v1/classify", json={"text": "ok", "private_field": sentinel})

    assert too_long.status_code == 422
    assert extra_field.status_code == 422
    assert sentinel not in too_long.text
    assert sentinel not in extra_field.text


def test_configured_review_confidence_threshold_is_applied(tmp_path, monkeypatch):
    model_path = tmp_path / "multiclass.joblib"
    joblib.dump({"model": MulticlassModel(), "classes": MulticlassModel.classes_, "version": "multi-v1"}, model_path)
    monkeypatch.setenv("PRIVATESMS_REVIEW_CONFIDENCE_THRESHOLD", "0.99")
    with TestClient(create_app(model_path=model_path, feedback_db_path=tmp_path / "feedback.sqlite3")) as client:
        result = client.post("/api/v1/classify", json={"text": "虚构验证码样例"}).json()
    assert result["category"] == "otp"
    assert result["needs_review"] is True


def test_api_rejects_out_of_range_confidence_configuration(monkeypatch):
    monkeypatch.setenv("PRIVATESMS_REVIEW_CONFIDENCE_THRESHOLD", "1.1")
    with pytest.raises(ValueError, match="PRIVATESMS_REVIEW_CONFIDENCE_THRESHOLD"):
        create_app()


@pytest.mark.parametrize("value", ["0", "-2", "many"])
def test_api_rejects_invalid_inference_thread_configuration(monkeypatch, value):
    monkeypatch.setenv("PRIVATESMS_INFERENCE_THREADS", value)
    with pytest.raises(ValueError, match="PRIVATESMS_INFERENCE_THREADS must be a positive integer"):
        create_app()


def test_api_applies_configured_thread_limit_for_process_lifetime(tmp_path, monkeypatch):
    model_path = tmp_path / "model.joblib"
    joblib.dump({"model": BinaryModel(), "classes": ["ham", "spam"], "version": "thread-test"}, model_path)
    monkeypatch.setenv("PRIVATESMS_INFERENCE_THREADS", "2")
    from threadpoolctl import threadpool_info
    import privatesms.api.app as api_module

    observed_pools = []
    original_predict = api_module.predict

    def inspect_worker_pool(*args, **kwargs):
        observed_pools.extend(threadpool_info())
        return original_predict(*args, **kwargs)

    monkeypatch.setattr(api_module, "predict", inspect_worker_pool)

    with TestClient(create_app(model_path=model_path, feedback_db_path=tmp_path / "feedback.sqlite3")) as client:
        assert client.post("/api/v1/classify", json={"text": "synthetic thread test"}).status_code == 200
    assert observed_pools
    assert all(pool["num_threads"] == 2 for pool in observed_pools), observed_pools
