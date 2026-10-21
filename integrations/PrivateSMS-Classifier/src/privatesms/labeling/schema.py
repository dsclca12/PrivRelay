from __future__ import annotations

from typing import Any


CATEGORIES = frozenset({"personal", "otp", "service", "transaction", "marketing", "suspicious", "uncertain"})
SOURCES = frozenset({"public", "teacher_synthetic", "teacher_assisted", "human"})


def validate_labeled_record(record: dict[str, Any]) -> dict[str, Any]:
    """Validate provenance while keeping teacher labels distinct from human truth."""
    if not isinstance(record, dict):
        raise ValueError("record must be an object")
    text = record.get("text")
    category = record.get("category", record.get("label"))
    source = record.get("source")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("record text must be a non-empty string")
    if category not in CATEGORIES:
        raise ValueError(f"category must be one of {sorted(CATEGORIES)}")
    if source not in SOURCES:
        raise ValueError(f"source must be one of {sorted(SOURCES)}")
    if source == "teacher_synthetic" and record.get("synthetic") is not True:
        raise ValueError("teacher_synthetic records must set synthetic=true")
    human_verified = record.get("human_verified")
    if "human_verified" in record and type(human_verified) is not bool:
        raise ValueError("human_verified must be a boolean")
    if source == "human" and human_verified is not True:
        raise ValueError("human records must explicitly set human_verified=true")
    if source in {"teacher_synthetic", "teacher_assisted"} and record.get("human_verified") is True:
        raise ValueError("teacher output cannot claim human_verified=true")
    cleaned = dict(record)
    cleaned["text"] = text.strip()
    cleaned["label"] = category
    cleaned["category"] = category
    cleaned.setdefault("human_verified", False)
    return cleaned
