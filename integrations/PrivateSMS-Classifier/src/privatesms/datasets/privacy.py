from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import unicodedata
from pathlib import Path

from .loaders import load_dataset, prepare_dataset


_REDACTIONS = (
    ("url", re.compile(r"(?i)\b(?:https?://|www\.)[^\s<>\]\[(){},!?;，。！？；、：]+"), "<URL>"),
    ("email", re.compile(r"(?i)\b[\w.+-]+@[\w.-]+\.[a-z]{2,}\b"), "<EMAIL>"),
    ("id_number", re.compile(r"(?<!\d)\d{6}(?:[ -]?\d{8})[ -]?\d{3}[ -]?[0-9Xx](?!\d)"), "<ID>"),
    ("bank_or_long_account", re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)"), "<ACCOUNT>"),
    ("mobile", re.compile(r"(?<!\d)(?:\+?86[ -]?)?1[3-9](?:[ -]?\d){9}(?!\d)"), "<PHONE>"),
)


def redact_text(text: str) -> tuple[str, dict[str, int]]:
    """Mask common direct identifiers; this is a heuristic, not full anonymization."""
    value = unicodedata.normalize("NFKC", text)
    counts: dict[str, int] = {}
    for name, pattern, replacement in _REDACTIONS:
        value, count = pattern.subn(replacement, value)
        if count:
            counts[name] = count
    return value, counts


def sanitize_public_dataset(
    input_path: str | Path,
    output_path: str | Path,
    *,
    confirm_public_source: bool,
) -> dict:
    """Write a local, identifier-redacted JSONL copy of a confirmed public dataset."""
    if not confirm_public_source:
        raise ValueError("Confirm that the source is public and permitted for local processing")
    source = Path(input_path).resolve()
    output = Path(output_path).resolve()
    raw_root = Path("data/raw").resolve()
    processed_root = Path("data/processed").resolve()
    try:
        source.relative_to(raw_root)
        output.relative_to(processed_root)
    except ValueError as exc:
        raise ValueError("Input must be under data/raw and output under data/processed") from exc
    if source == output or output.exists():
        raise FileExistsError("Output must be a new file; refusing to overwrite existing data")
    if output.suffix.casefold() not in {".jsonl", ".ndjson"}:
        raise ValueError("Output must use .jsonl or .ndjson")

    dataset, report = load_dataset(source)
    redacted_rows: list[tuple[str, str]] = []
    redactions_by_pair: dict[tuple[str, str], dict[str, int]] = {}
    for text, label in zip(dataset.texts, dataset.labels):
        clean, counts = redact_text(text)
        redacted_rows.append((clean, label))
        redactions_by_pair.setdefault((clean, label), counts)
    sanitized, sanitized_report = prepare_dataset(redacted_rows)
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{output.name}.", suffix=".tmp", dir=output.parent)
    temp_path = Path(temp_name)
    totals: dict[str, int] = {}
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            for text, label in zip(sanitized.texts, sanitized.labels):
                counts = redactions_by_pair.get((text, label), {})
                for name, count in counts.items():
                    totals[name] = totals.get(name, 0) + count
                record = {
                    "text": text,
                    "label": label,
                    "source": "public",
                    "source_sha256": source_hash,
                    "redaction_version": "common-identifiers-v1",
                    "redactions": counts,
                }
                handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_path, 0o600)
        os.link(temp_path, output)
        temp_path.unlink()
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise

    return {
        "input_sha256": source_hash,
        "output": str(output),
        "input_rows": report.input_rows,
        "output_rows": len(sanitized),
        "exact_duplicates_removed": report.exact_duplicates,
        "conflicting_template_rows_removed": report.conflicting_template_rows,
        "post_redaction_exact_duplicates_removed": sanitized_report.exact_duplicates,
        "post_redaction_conflicting_template_rows_removed": sanitized_report.conflicting_template_rows,
        "redaction_counts": totals,
    }
