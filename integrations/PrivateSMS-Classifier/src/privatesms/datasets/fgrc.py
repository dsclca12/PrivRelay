from __future__ import annotations

import json
import os
import random
import tempfile
import zipfile
from collections import Counter
from pathlib import Path


_MEMBER = "message/finetuning_initial.json"
_RISK_LABELS = {
    "冒充公检法及政府机关类",
    "冒充军警购物类诈骗",
    "冒充电商物流客服类",
    "冒充领导、熟人类",
    "网络婚恋、交友类",
    "网黑案件",
    "虚假信用服务类",
    "虚假网络投资理财类",
    "虚假购物、服务类",
}
_LABELS = _RISK_LABELS | {"无风险"}


def import_fgrc_scd_sms(
    source: str | Path,
    output: str | Path,
    *,
    max_per_class: int = 250,
    seed: int = 42,
    risk_only_as_suspicious: bool = False,
) -> dict:
    """Convert a capped FGRC-SCD sample into explicitly training-only JSONL."""
    if max_per_class < 1:
        raise ValueError("max_per_class must be positive")
    source_path = Path(source)
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    try:
        with zipfile.ZipFile(source_path) as archive:
            try:
                member = archive.getinfo(_MEMBER)
            except KeyError as exc:
                raise ValueError(f"FGRC-SCD archive is missing {_MEMBER}") from exc
            if member.file_size > 64 * 1024 * 1024:
                raise ValueError("FGRC-SCD SMS member exceeds the 64 MiB import limit")
            records = json.loads(archive.read(member))
    except (zipfile.BadZipFile, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError("FGRC-SCD archive is invalid") from exc
    if not isinstance(records, list):
        raise ValueError("FGRC-SCD SMS member must contain a JSON array")

    grouped: dict[str, list[tuple[str, str]]] = {label: [] for label in sorted(_LABELS)}
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("FGRC-SCD records must be JSON objects")
        label = record.get("风险类别")
        text = record.get("文本")
        if label not in _LABELS or not isinstance(text, str) or not text.strip():
            raise ValueError("FGRC-SCD record has an unsupported label or empty text")
        grouped[label].append((text.strip(), "ham" if label == "无风险" else "spam"))

    rng = random.Random(seed)
    selected: list[tuple[str, str, str]] = []
    source_counts = {label: 0 for label in sorted(grouped)}
    risk_pools = {label: list(rows) for label, rows in grouped.items() if label != "无风险"}
    for rows in risk_pools.values():
        rng.shuffle(rows)
    risk_target = min(max_per_class, sum(map(len, risk_pools.values())))

    if risk_only_as_suspicious:
        selected_risk = 0
    else:
        benign = grouped["无风险"]
        for text, target_label in rng.sample(benign, min(max_per_class, len(benign))):
            selected.append((text, target_label, "无风险"))
            source_counts["无风险"] += 1
        selected_risk = sum(target_label == "spam" for _, target_label, _ in selected)

    while selected_risk < risk_target:
        for source_label in sorted(risk_pools):
            if not risk_pools[source_label]:
                continue
            text, _ = risk_pools[source_label].pop()
            target_label = "suspicious" if risk_only_as_suspicious else "spam"
            selected.append((text, target_label, source_label))
            source_counts[source_label] += 1
            selected_risk += 1
            if selected_risk >= risk_target:
                break
    rng.shuffle(selected)

    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    temporary = Path(temp_name)
    output_labels: Counter[str] = Counter()
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            for text, target_label, source_label in selected:
                handle.write(json.dumps({
                    "text": text,
                    "label": target_label,
                    "source": "fgrc_synthetic",
                    "source_dataset": "fgrc-scd-sms",
                    "source_category": source_label,
                    "synthetic": True,
                    "training_only": True,
                }, ensure_ascii=False) + "\n")
                output_labels[target_label] += 1
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise

    return {
        "source_dataset": "fgrc-scd-sms",
        "source_member": _MEMBER,
        "source_rows": len(records),
        "selected_rows": len(selected),
        "source_label_counts": source_counts,
        "mapped_label_counts": dict(output_labels),
        "max_per_class": max_per_class,
        "max_per_class_means": "suspicious_risk_samples" if risk_only_as_suspicious else "mapped_ham_or_spam_label",
        "mapping_mode": "risk_only_suspicious" if risk_only_as_suspicious else "binary_ham_spam",
        "seed": seed,
        "synthetic": True,
        "training_only": True,
        "independent_test_eligible": False,
        "output": str(target),
    }
