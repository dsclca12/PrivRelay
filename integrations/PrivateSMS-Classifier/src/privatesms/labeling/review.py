from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .schema import CATEGORIES


def review_teacher_suggestions(
    *,
    input_path: str | Path,
    output_path: str | Path,
    decision_provider: Callable[[dict, int], str | None],
    max_records: int = 100,
) -> dict:
    """Collect local human decisions; no network calls are made by this function."""
    if not 1 <= max_records <= 1000:
        raise ValueError("max_records must be between 1 and 1000")
    source = Path(input_path)
    target = Path(output_path)
    if source.resolve() == target.resolve():
        raise ValueError("review output must not overwrite its input")
    rows = []
    with source.open(encoding="utf-8-sig") as handle:
        for line_no, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL at line {line_no}") from exc
            if not isinstance(row, dict):
                raise ValueError(f"JSONL record at line {line_no} must be an object")
            if (
                row.get("source") == "teacher_assisted"
                and row.get("human_verified") is False
                and row.get("training_only") is True
                and row.get("synthetic") is not True
            ):
                rows.append(row)
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    reviewed = []
    considered = rows[:max_records]
    for index, row in enumerate(considered):
        decision = decision_provider(row, index)
        if decision is None or not str(decision).strip():
            continue
        category = str(decision).strip().casefold()
        if category not in CATEGORIES:
            raise ValueError(f"Invalid reviewed category for row {index}")
        accepted = dict(row)
        accepted["label"] = category
        accepted["category"] = category
        accepted["source"] = "human"
        accepted["synthetic"] = False
        accepted["training_only"] = True
        accepted["human_verified"] = True
        accepted["human_reviewed"] = True
        accepted["label_status"] = "human_verified"
        accepted["provenance"] = {
            **(row.get("provenance") if isinstance(row.get("provenance"), dict) else {}),
            "review_source_sha256": source_hash,
            "reviewed_from_teacher_category": row.get("category"),
            "reviewed_at": datetime.now(timezone.utc).isoformat(),
        }
        reviewed.append(accepted)

    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = target.with_suffix(target.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        for row in reviewed:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, target)
    os.chmod(target, 0o600)
    return {"suggestions_reviewed": len(considered), "human_verified_rows": len(reviewed), "output": str(target)}
