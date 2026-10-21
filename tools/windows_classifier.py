"""Loopback-only inference harness for upstream's Windows fchmod incompatibility.

Uses upstream ONNX loading/predict, preserving calibration/review metadata.
No feedback endpoints or request persistence. Deploy the upstream Linux container
for normal hosting. Run with the upstream package and uvicorn installed.
"""
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from pydantic import BaseModel, Field
from privatesms.inference import load_model, predict
from threadpoolctl import threadpool_limits


@asynccontextmanager
async def lifespan(app):
    app.state.bundle = load_model(os.environ["PRIVATESMS_MODEL_PATH"])
    yield
    app.state.bundle = None


app = FastAPI(lifespan=lifespan)


class Request(BaseModel):
    text: str = Field(min_length=1, max_length=4096)
    sender: str | None = Field(default=None, max_length=64)


@app.get("/healthz")
def health():
    return {"status": "ok"}


@app.post("/api/v1/classify")
def classify(request: Request):
    with threadpool_limits(limits=4):
        result = predict(app.state.bundle, request.text)
    return {key: result[key] for key in (
        "category", "confidence", "spam_score", "confidence_calibrated",
        "needs_review", "model_version", "is_spam")}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=18788, access_log=False)
