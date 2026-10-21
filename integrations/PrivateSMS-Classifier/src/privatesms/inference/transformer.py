from __future__ import annotations

import json
import math
from pathlib import Path
from privatesms.text_normalization import normalize_verification_codes


class TransformerPredictor:
    def __init__(self, *, model, tokenizer, classes: list[str], max_length: int = 128, batch_size: int = 16, temperature: float = 1.0):
        if not math.isfinite(temperature) or not 0.05 <= temperature <= 20.0:
            raise ValueError("temperature must be between 0.05 and 20")
        self.model = model
        self.tokenizer = tokenizer
        self.classes_ = list(classes)
        self.max_length = max_length
        self.batch_size = batch_size
        self.temperature = temperature

    def predict_proba(self, texts: list[str]):
        import torch

        self.model.eval()
        result = []
        with torch.inference_mode():
            for start in range(0, len(texts), self.batch_size):
                batch_texts = [normalize_verification_codes(text) for text in texts[start:start + self.batch_size]]
                batch = self.tokenizer(batch_texts, truncation=True, max_length=self.max_length, padding=True, return_tensors="pt")
                logits = self.model(**batch).logits
                result.extend(torch.softmax(logits / self.temperature, dim=-1).cpu().tolist())
        return result


def load_transformer_bundle(path: str | Path) -> dict:
    try:
        from transformers import AutoModelForSequenceClassification, AutoTokenizer
    except ImportError as exc:
        raise RuntimeError("Install the optional transformer dependencies with `pip install -e '.[transformer]'`") from exc
    target = Path(path)
    metadata = json.loads((target / "metadata.json").read_text(encoding="utf-8"))
    best_dir = target / "best_model"
    tokenizer = AutoTokenizer.from_pretrained(best_dir, local_files_only=True)
    model = AutoModelForSequenceClassification.from_pretrained(best_dir, local_files_only=True)
    predictor = TransformerPredictor(
        model=model,
        tokenizer=tokenizer,
        classes=metadata["classes"],
        max_length=metadata["max_length"],
        temperature=metadata.get("calibration_temperature", 1.0),
    )
    return {**metadata, "model": predictor}
