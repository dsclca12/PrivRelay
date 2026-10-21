from __future__ import annotations

import math
from pathlib import Path
from privatesms.text_normalization import normalize_verification_codes


class OnnxPredictor:
    def __init__(self, *, session, tokenizer, classes: list[str], max_length: int = 128, batch_size: int = 16, temperature: float = 1.0):
        if not math.isfinite(temperature) or not 0.05 <= temperature <= 20.0:
            raise ValueError("temperature must be between 0.05 and 20")
        self.session = session
        self.tokenizer = tokenizer
        self.classes_ = list(classes)
        self.max_length = max_length
        self.batch_size = batch_size
        self.temperature = temperature

    def predict_proba(self, texts: list[str]):
        import numpy as np

        output = []
        input_names = {item.name for item in self.session.get_inputs()}
        for start in range(0, len(texts), self.batch_size):
            batch_texts = [normalize_verification_codes(text) for text in texts[start:start + self.batch_size]]
            encoded = self.tokenizer(batch_texts, truncation=True, max_length=self.max_length, padding=True, return_tensors="np")
            feeds = {name: encoded[name].astype(np.int64, copy=False) for name in input_names if name in encoded}
            logits = self.session.run(["logits"], feeds)[0]
            logits = logits / self.temperature
            logits = logits - logits.max(axis=-1, keepdims=True)
            exp = np.exp(logits)
            output.extend((exp / exp.sum(axis=-1, keepdims=True)).tolist())
        return output


def load_onnx_bundle(path: str | Path, *, quantized: bool | None = None, threads: int | None = None) -> dict:
    try:
        import onnxruntime as ort
        from transformers import AutoTokenizer
    except ImportError as exc:
        raise RuntimeError("Install optional CPU ONNX and tokenizer dependencies with `pip install -e '.[onnx,transformer]'`") from exc
    import json
    import os

    target = Path(path)
    metadata = json.loads((target / "metadata.json").read_text(encoding="utf-8"))
    quantized = os.getenv("PRIVATESMS_ONNX_QUANTIZED", "1") == "1" if quantized is None else quantized
    if quantized and metadata.get("quantization") == "disabled-copy":
        raise ValueError("INT8 inference requested, but this ONNX bundle was exported with quantization disabled")
    if not quantized and not (target / "model.onnx").is_file() and (target / "model.int8.onnx").is_file():
        raise ValueError("This public model bundle contains INT8 weights only; set PRIVATESMS_ONNX_QUANTIZED=1")
    filename = "model.int8.onnx" if quantized else "model.onnx"
    model_file = target / filename
    if not model_file.is_file():
        raise FileNotFoundError(model_file)
    options = ort.SessionOptions()
    options.intra_op_num_threads = threads or int(os.getenv("PRIVATESMS_INFERENCE_THREADS", "4"))
    options.inter_op_num_threads = 1
    options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    session = ort.InferenceSession(str(model_file), sess_options=options, providers=["CPUExecutionProvider"])
    if "CPUExecutionProvider" not in session.get_providers():
        raise RuntimeError("ONNX Runtime CPUExecutionProvider is not available")
    tokenizer = AutoTokenizer.from_pretrained(target, local_files_only=True)
    predictor = OnnxPredictor(
        session=session,
        tokenizer=tokenizer,
        classes=metadata["classes"],
        max_length=metadata["max_length"],
        temperature=metadata.get("calibration_temperature", 1.0),
    )
    threshold_key = "decision_threshold_int8" if quantized else "decision_threshold_float"
    if threshold_key in metadata:
        metadata["decision_threshold"] = metadata[threshold_key]
    metadata["version"] = metadata.get("version", "onnx-v1") + ("-int8" if quantized else "-onnx")
    return {**metadata, "model": predictor}
