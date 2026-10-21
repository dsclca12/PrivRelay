from __future__ import annotations

import os
import secrets
import math
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from privatesms.inference import load_model, predict
from privatesms.feedback import FeedbackStore
from privatesms.inference.registry import resolve_model_path


Category = Literal["personal", "otp", "service", "transaction", "marketing", "suspicious", "uncertain"]


class ClassifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=4096)
    sender: str | None = Field(default=None, max_length=64)


class ClassifyResponse(BaseModel):
    category: Category
    is_spam: bool
    spam_score: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    confidence_calibrated: bool
    needs_review: bool
    model_version: str


class SmsScoreRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    address: str = Field(default="", max_length=64)
    body: str = Field(min_length=1, max_length=4096)
    timestamp: int = Field(ge=0)
    localScore: float = Field(ge=0, le=1)
    threshold: float = Field(ge=0, le=1)
    profile: Literal["strict", "balanced", "conservative"]
    modelVersion: str = Field(min_length=1, max_length=100)


class SmsScoreResponse(BaseModel):
    action: Literal["allow", "block"]
    score: float = Field(ge=0, le=1)
    reason: str
    modelVersion: str
    thresholdUsed: float = Field(ge=0, le=1)
    category: Category
    needsReview: bool


class FeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=4096)
    feedback_type: Literal["false_spam", "missed_spam", "wrong_category"]
    predicted_category: Category | None = None
    corrected_category: Category
    model_version: str = Field(min_length=1, max_length=100)


class FeedbackReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["approve", "reject"]
    category: Category | None = None


def _probability_setting(name: str, default: float) -> float:
    raw = os.getenv(name)
    value = default if raw is None or not raw.strip() else float(raw)
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError(f"{name} must be between 0 and 1")
    return value


def _positive_integer_setting(name: str, default: int) -> int:
    raw = os.getenv(name)
    try:
        value = default if raw is None or not raw.strip() else int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a positive integer") from exc
    if value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _registry_version_for_path(model_path: str | Path, registry_path: str | Path) -> str | None:
    versions_root = (Path(registry_path) / "versions").resolve()
    try:
        relative = Path(model_path).resolve().relative_to(versions_root)
    except ValueError:
        return None
    return relative.parts[0] if relative.parts else None


def create_app(*, model_path: str | Path | None = None, api_key: str | None = None, feedback_db_path: str | Path | None = None) -> FastAPI:
    configured_registry_path = Path(os.getenv("PRIVATESMS_MODEL_REGISTRY", "artifacts/model_registry"))
    configured_model_path = resolve_model_path(
        model_path=model_path,
        registry_path=configured_registry_path,
        fallback=os.getenv("PRIVATESMS_DEFAULT_MODEL_PATH", "artifacts/baseline.joblib"),
    )
    configured_api_key = os.getenv("PRIVATESMS_API_KEY") if api_key is None else api_key
    configured_feedback_db = Path(feedback_db_path or os.getenv("PRIVATESMS_FEEDBACK_DB", "data/feedback.sqlite3"))
    configured_inference_threads = _positive_integer_setting("PRIVATESMS_INFERENCE_THREADS", 4)
    inference_thread_state = threading.local()
    configured_review_confidence = _probability_setting("PRIVATESMS_REVIEW_CONFIDENCE_THRESHOLD", 0.6)
    configured_decision_threshold = os.getenv("PRIVATESMS_DECISION_THRESHOLD")
    decision_threshold = (
        _probability_setting("PRIVATESMS_DECISION_THRESHOLD", 0.5)
        if configured_decision_threshold is not None and configured_decision_threshold.strip()
        else None
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        from threadpoolctl import threadpool_limits

        # PyTorch requires its thread limit before model execution. ONNX configures
        # its own pool from the same environment setting during session creation.
        model_target = Path(configured_model_path)
        if model_target.is_dir() and not (model_target / "model.onnx").is_file() and not (model_target / "model.int8.onnx").is_file():
            try:
                import torch
            except ImportError:
                pass
            else:
                torch.set_num_threads(configured_inference_threads)
        app.state.bundle = load_model(configured_model_path)
        # Apply after loading: model libraries may load their OpenMP/BLAS pools only
        # while deserializing the model. Keep the limiter alive for the service.
        limiter = threadpool_limits(limits=configured_inference_threads)
        try:
            registry_version = _registry_version_for_path(configured_model_path, configured_registry_path)
            if registry_version:
                app.state.bundle["registry_version"] = registry_version
            app.state.feedback_store = FeedbackStore(configured_feedback_db)
            yield
        finally:
            limiter.restore_original_limits()
            app.state.bundle = None
            app.state.feedback_store = None

    app = FastAPI(title="PrivateSMS Classifier", version="0.2.0", lifespan=lifespan)

    @app.exception_handler(RequestValidationError)
    async def validation_error_without_request_data(_: Request, exc: RequestValidationError):
        # Pydantic errors include the rejected input by default. Never reflect SMS
        # bodies (or other submitted fields) into responses that may be logged.
        safe_errors = [
            {key: error[key] for key in ("type", "loc", "msg") if key in error}
            for error in exc.errors()
        ]
        return JSONResponse(status_code=422, content={"detail": safe_errors})

    @app.get("/healthz")
    def healthz():
        bundle = getattr(app.state, "bundle", None)
        if bundle is None:
            raise HTTPException(status_code=503, detail="model not loaded")
        return {"status": "ok", "model_version": bundle.get("registry_version", bundle.get("version", "unknown"))}

    @app.get("/test", include_in_schema=False)
    def test_page():
        return FileResponse(Path(__file__).with_name("test.html"), media_type="text/html; charset=utf-8")

    def classify_text(bundle: dict, text: str):
        # Starlette runs sync routes in worker threads. OpenMP's limit is
        # thread-local, so initialize it on every worker that handles inference.
        if getattr(inference_thread_state, "limit", None) != configured_inference_threads:
            from threadpoolctl import threadpool_limits

            inference_thread_state.limiter = threadpool_limits(limits=configured_inference_threads)
            inference_thread_state.limit = configured_inference_threads
        result = predict(
            bundle,
            text,
            threshold=decision_threshold,
            review_confidence_threshold=configured_review_confidence,
        )
        category = result["category"]
        needs_review = result["needs_review"]
        if category in {"ham", "spam"}:
            category = "uncertain"
            needs_review = True
        return result, category, needs_review

    @app.post("/api/v1/classify", response_model=ClassifyResponse)
    def classify(payload: ClassifyRequest, x_api_key: str | None = Header(default=None)):
        if configured_api_key and not secrets.compare_digest(x_api_key or "", configured_api_key):
            raise HTTPException(status_code=401, detail="invalid API key")
        bundle = getattr(app.state, "bundle", None)
        if bundle is None:
            raise HTTPException(status_code=503, detail="model not loaded")
        result, category, needs_review = classify_text(bundle, payload.text)
        category_is_business_class = result["category"] not in {"ham", "spam"}
        return ClassifyResponse(
            category=category,
            is_spam=result["is_spam"],
            spam_score=result["spam_score"],
            confidence=result["confidence"],
            confidence_calibrated=result["confidence_calibrated"] and category_is_business_class,
            needs_review=needs_review,
            model_version=bundle.get("registry_version", result["model_version"]),
        )

    @app.post("/sms/score", response_model=SmsScoreResponse)
    def score_sms(payload: SmsScoreRequest, x_api_key: str | None = Header(default=None)):
        if configured_api_key and not secrets.compare_digest(x_api_key or "", configured_api_key):
            raise HTTPException(status_code=401, detail="invalid API key")
        bundle = getattr(app.state, "bundle", None)
        if bundle is None:
            raise HTTPException(status_code=503, detail="model not loaded")
        result, category, needs_review = classify_text(bundle, payload.body)
        # The Android caller can only accept allow/block. Never hard-block on a
        # binary model, an uncalibrated business category, or a review-required
        # prediction. This keeps the compatibility adapter fail-open until a
        # validated seven-class model is active.
        can_block = (
            result["is_spam"]
            and category in {"marketing", "suspicious"}
            and result["confidence_calibrated"]
            and not needs_review
        )
        action = "block" if can_block else "allow"
        if can_block:
            reason = f"risk_category:{category}"
        elif needs_review:
            reason = f"review_required:{category}"
        elif not result["confidence_calibrated"]:
            reason = "uncalibrated_category_allow"
        else:
            reason = "below_safe_block_gate"
        used_threshold = decision_threshold
        if used_threshold is None:
            used_threshold = bundle.get("decision_threshold", 0.5)
        return SmsScoreResponse(
            action=action,
            score=result["spam_score"],
            reason=reason,
            modelVersion=bundle.get("registry_version", result["model_version"]),
            thresholdUsed=used_threshold,
            category=category,
            needsReview=needs_review,
        )

    def authorize(x_api_key: str | None, *, require_configured_key: bool = False):
        if require_configured_key and not configured_api_key:
            raise HTTPException(status_code=503, detail="feedback routes require PRIVATESMS_API_KEY")
        if configured_api_key and not secrets.compare_digest(x_api_key or "", configured_api_key):
            raise HTTPException(status_code=401, detail="invalid API key")

    @app.post("/api/v1/feedback", status_code=202)
    def submit_feedback(payload: FeedbackRequest, x_api_key: str | None = Header(default=None)):
        authorize(x_api_key, require_configured_key=True)
        store = getattr(app.state, "feedback_store", None)
        if store is None:
            raise HTTPException(status_code=503, detail="feedback store not ready")
        benign = {"personal", "otp", "service", "transaction"}
        risk = {"marketing", "suspicious"}
        if payload.feedback_type == "false_spam" and payload.corrected_category not in benign:
            raise HTTPException(status_code=422, detail="false_spam requires a benign corrected_category")
        if payload.feedback_type == "missed_spam" and payload.corrected_category not in risk:
            raise HTTPException(status_code=422, detail="missed_spam requires marketing or suspicious")
        feedback_id = store.submit(
            text=payload.text,
            feedback_type=payload.feedback_type,
            predicted_category=payload.predicted_category,
            corrected_category=payload.corrected_category,
            model_version=payload.model_version,
        )
        return {"feedback_id": feedback_id, "status": "pending"}

    @app.get("/api/v1/feedback/pending")
    def pending_feedback(limit: int = 100, x_api_key: str | None = Header(default=None)):
        authorize(x_api_key, require_configured_key=True)
        store = getattr(app.state, "feedback_store", None)
        if store is None:
            raise HTTPException(status_code=503, detail="feedback store not ready")
        try:
            return {"items": store.pending(limit=limit)}
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/v1/feedback/{feedback_id}/review")
    def review_feedback(feedback_id: str, payload: FeedbackReviewRequest, x_api_key: str | None = Header(default=None)):
        authorize(x_api_key, require_configured_key=True)
        store = getattr(app.state, "feedback_store", None)
        if store is None:
            raise HTTPException(status_code=503, detail="feedback store not ready")
        if payload.decision == "approve" and payload.category is None:
            raise HTTPException(status_code=422, detail="approved feedback requires a human-reviewed category")
        changed = store.review(feedback_id, decision=payload.decision, category=payload.category)
        if not changed:
            raise HTTPException(status_code=404, detail="pending feedback not found")
        return {"feedback_id": feedback_id, "status": "approved" if payload.decision == "approve" else "rejected"}

    return app


app = create_app()
