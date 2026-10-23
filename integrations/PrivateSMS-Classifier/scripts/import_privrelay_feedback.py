#!/usr/bin/env python3
"""Convert an explicitly authorized PrivRelay training export to local JSONL."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path

CATEGORIES = {"personal", "otp", "service", "transaction", "marketing", "suspicious", "uncertain"}


def convert(source: Path, target: Path, authorization_reference: str) -> int:
    raw = source.read_bytes()
    export = json.loads(raw)
    if not isinstance(export, dict) or export.get("schema_version") != 1:
        raise ValueError("unsupported PrivRelay export schema")
    if export.get("purpose") != "training" or export.get("include_text") is not True:
        raise ValueError("export must explicitly be a training export with message text")
    if export.get("consent") is not True or not isinstance(export.get("export_id"), str) or not export.get("export_id"):
        raise ValueError("export is missing its server-issued consent receipt")
    samples = export.get("samples")
    if not isinstance(samples, list):
        raise ValueError("samples must be a list")
    source_digest = hashlib.sha256(raw).hexdigest()
    group = "privrelay_" + source_digest[:16]
    rows: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    for index, sample in enumerate(samples, 1):
        if not isinstance(sample, dict):
            raise ValueError(f"sample {index} must be an object")
        text = sample.get("text")
        label = sample.get("label")
        if not isinstance(text, str) or not text.strip() or len(text) > 100_000:
            raise ValueError(f"sample {index} has invalid or missing text")
        if not isinstance(label, str) or label not in CATEGORIES:
            raise ValueError(f"sample {index} has unsupported label")
        key = (text.strip(), label)
        if key in seen:
            continue
        seen.add(key)
        rows.append({
            "text": text.strip(), "label": label, "category": label,
            "source": "human", "human_verified": True, "synthetic": False,
            "training_only": True, "feedback_export": True,
            "training_group": group,
            "provenance": {
                "kind": "privrelay_feedback_export", "source_sha256": source_digest,
                "export_id": export["export_id"], "authorization_reference": authorization_reference,
            },
        })
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if target.exists():
        raise FileExistsError(f"refusing to overwrite existing dataset: {target}")
    fd, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return len(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("export", type=Path, help="locally downloaded PrivRelay export JSON")
    parser.add_argument("output", type=Path, help="new private JSONL dataset path")
    parser.add_argument("--authorization-reference", required=True, help="operator record for the data-use authorization")
    args = parser.parse_args()
    if not args.authorization_reference.strip():
        parser.error("--authorization-reference must not be empty")
    try:
        count = convert(args.export, args.output, args.authorization_reference.strip())
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(f"Imported {count} deduplicated samples to {args.output}; no model was trained or uploaded.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
