from __future__ import annotations

import resource
import statistics
import time
import math
from pathlib import Path

from .metrics import evaluate


def _nearest_rank(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(percentile * len(ordered)) - 1))
    return ordered[index]


def _latencies(predictor, texts: list[str], *, limit: int = 128) -> dict:
    sample = texts[:limit]
    for text in sample[:5]:
        predictor.predict_proba([text])
    timings = []
    for text in sample:
        start = time.perf_counter()
        predictor.predict_proba([text])
        timings.append((time.perf_counter() - start) * 1000)
    return {
        "samples": len(timings),
        "p50_ms": statistics.median(timings) if timings else None,
        "p95_ms": _nearest_rank(timings, 0.95),
    }


def benchmark_predictor(predictor, texts: list[str], labels: list[str], *, threshold: float, model_path: str | Path, latency_limit: int = 128, category_decision: str = "risk_threshold") -> dict:
    metrics = evaluate(predictor, texts, labels, threshold=threshold, category_decision=category_decision)
    max_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    model_bytes = sum(p.stat().st_size for p in Path(model_path).rglob("*") if p.is_file()) if Path(model_path).is_dir() else Path(model_path).stat().st_size
    return {
        "metrics": metrics,
        "latency_single_sample": _latencies(predictor, texts, limit=latency_limit),
        "process_peak_rss_kib": max_rss,
        "model_artifact_bytes": model_bytes,
        "memory_scope": "process peak RSS includes libraries and previously loaded models; not a per-model measurement",
    }
