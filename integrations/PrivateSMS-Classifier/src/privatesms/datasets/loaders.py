from __future__ import annotations

import csv
import hashlib
import json
import random
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Iterable


_URL = re.compile(r"(?i)\b(?:https?://|www\.)\S+")
_EMAIL = re.compile(r"(?i)\b[\w.+-]+@[\w.-]+\.[a-z]{2,}\b")
_PHONE = re.compile(r"(?<!\w)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\w)")
_NUMBER = re.compile(r"\d+(?:[.,:]\d+)*")
_SPACE = re.compile(r"\s+")
_NEAR_DUPLICATE_MIN_CHARS = 30
_NEAR_DUPLICATE_COSINE_THRESHOLD = 0.96
_NEAR_DUPLICATE_BLOCK_SIZE = 128
_CATEGORIES = {"personal", "otp", "service", "transaction", "marketing", "suspicious", "uncertain"}
_SOURCES = {"public", "teacher_synthetic", "teacher_assisted", "fgrc_synthetic", "human"}


@dataclass(frozen=True)
class SmsDataset:
    texts: list[str]
    labels: list[str]
    template_ids: list[str]
    training_only: list[bool]
    synthetic_flags: list[bool]
    supplement_groups: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.supplement_groups and self.texts:
            object.__setattr__(
                self,
                "supplement_groups",
                ["supplement" if self.training_only[i] or self.synthetic_flags[i] else "public" for i in range(len(self.texts))],
            )
        if len(self.supplement_groups) != len(self.texts):
            raise ValueError("supplement_groups must match the number of dataset rows")

    def __len__(self) -> int:
        return len(self.texts)


@dataclass(frozen=True)
class DatasetReport:
    input_rows: int
    kept_rows: int
    empty_rows: int
    exact_duplicates: int
    conflicting_template_rows: int
    label_counts: dict[str, int]
    excluded_synthetic_rows: int = 0
    included_synthetic_rows: int = 0
    excluded_training_only_rows: int = 0
    excluded_training_only_overlap_rows: int = 0
    included_training_only_rows: int = 0
    near_duplicate_template_merges: int = 0
    near_duplicate_min_chars: int = _NEAR_DUPLICATE_MIN_CHARS
    near_duplicate_similarity_threshold: float = _NEAR_DUPLICATE_COSINE_THRESHOLD


def normalize_text(text: str, *, template: bool = False) -> str:
    """Normalize Unicode and mask identifiers for stable duplicate grouping."""
    value = unicodedata.normalize("NFKC", str(text)).strip().casefold()
    value = _URL.sub(" <url> ", value)
    value = _EMAIL.sub(" <email> ", value)
    value = _PHONE.sub(" <phone> ", value)
    if template:
        value = _NUMBER.sub(" <num> ", value)
    return _SPACE.sub(" ", value).strip()


def _merge_near_duplicate_templates(groups: dict[str, list[tuple]]) -> tuple[dict[str, list[tuple]], int]:
    """Join long, near-identical templates so trivial edits cannot cross splits."""
    from sklearn.feature_extraction.text import TfidfVectorizer

    candidates = [(key, rows) for key, rows in groups.items() if len(normalize_text(rows[0][0], template=True)) >= _NEAR_DUPLICATE_MIN_CHARS]
    if len(candidates) < 2:
        return groups, 0
    texts = [normalize_text(rows[0][0], template=True) for _, rows in candidates]
    matrix = TfidfVectorizer(analyzer="char", ngram_range=(3, 5), min_df=1, max_features=200_000, lowercase=False).fit_transform(texts)
    parents = list(range(len(candidates)))

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(left: int, right: int) -> None:
        root_left, root_right = find(left), find(right)
        if root_left != root_right:
            parents[max(root_left, root_right)] = min(root_left, root_right)

    for start in range(0, len(candidates), _NEAR_DUPLICATE_BLOCK_SIZE):
        similarities = (matrix[start:start + _NEAR_DUPLICATE_BLOCK_SIZE] @ matrix.T).tocoo()
        for row, column, similarity in zip(similarities.row, similarities.col, similarities.data):
            left, right = start + int(row), int(column)
            if left < right and similarity >= _NEAR_DUPLICATE_COSINE_THRESHOLD:
                union(left, right)

    clusters: dict[int, list[int]] = defaultdict(list)
    for index in range(len(candidates)):
        clusters[find(index)].append(index)
    if all(len(cluster) == 1 for cluster in clusters.values()):
        return groups, 0

    candidate_index = {key: index for index, (key, _) in enumerate(candidates)}
    merged: dict[str, list[tuple]] = {}
    emitted_roots: set[int] = set()
    for key, rows in groups.items():
        if key not in candidate_index:
            merged[key] = rows
            continue
        root = find(candidate_index[key])
        if root in emitted_roots:
            continue
        emitted_roots.add(root)
        member_keys = [candidates[index][0] for index in clusters[root]]
        combined_key = "\n".join(sorted(member_keys))
        merged[combined_key] = [row for member_key in member_keys for row in groups[member_key]]
    return merged, len(candidates) - len(clusters)


def _label(value: object) -> str:
    text = str(value).strip().casefold()
    if text in {"0", "ham", "normal", "legitimate", "非垃圾", "正常"}:
        return "ham"
    if text in {"1", "spam", "junk", "垃圾", "垃圾短信"}:
        return "spam"
    if text in _CATEGORIES:
        return text
    raise ValueError(f"Unsupported SMS category/label {value!r}")


def _read_rows(
    path: Path,
    text_column: str | None,
    label_column: str | None,
    *,
    include_synthetic: bool,
    include_feedback: bool,
    include_teacher_data: bool,
) -> tuple[list[tuple], int, int]:
    suffix = path.suffix.casefold()
    if suffix in {".jsonl", ".ndjson"}:
        rows = []
        excluded_synthetic = 0
        excluded_training_only = 0
        with path.open(encoding="utf-8-sig") as handle:
            for line_no, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                    if not isinstance(obj, dict):
                        raise ValueError(f"JSONL record at line {line_no} must be an object")
                    if obj.get("record_type") == "usage":
                        continue
                    synthetic = obj.get("synthetic") is True
                    source = obj.get("source")
                    if source is not None and (not isinstance(source, str) or source not in _SOURCES):
                        raise ValueError(f"Unsupported record source at line {line_no}")
                    if "human_verified" in obj and type(obj["human_verified"]) is not bool:
                        raise ValueError(f"human_verified at line {line_no} must be a boolean")
                    teacher_source = isinstance(source, str) and source in {"teacher_synthetic", "teacher_assisted"}
                    human_verified = obj.get("human_verified") is True
                    if source == "human" and not human_verified:
                        raise ValueError(f"Human-labeled record at line {line_no} must explicitly set human_verified=true")
                    if source == "fgrc_synthetic" and (not synthetic or obj.get("training_only") is not True):
                        raise ValueError(f"FGRC-SCD record at line {line_no} must be synthetic and training-only")
                    if teacher_source and human_verified:
                        raise ValueError(f"Teacher record at line {line_no} cannot be human-verified")
                    if obj.get("feedback_export") is True and (source != "human" or not human_verified):
                        raise ValueError(f"Feedback export at line {line_no} must be human-verified")
                    if obj.get("human_reviewed") is True and (source != "human" or not human_verified or obj.get("training_only") is not True):
                        raise ValueError(f"Human-reviewed record at line {line_no} must be verified and training-only")
                    if synthetic and not include_synthetic:
                        excluded_synthetic += 1
                        continue
                    teacher_unverified = teacher_source and not human_verified
                    feedback = source == "human" and human_verified and (obj.get("feedback_export") is True or obj.get("human_reviewed") is True) and obj.get("training_only") is True
                    training_only = synthetic or obj.get("training_only") is True or obj.get("feedback_export") is True or teacher_unverified
                    allowed_training_only = (
                        (synthetic and include_synthetic)
                        or (feedback and include_feedback)
                        or (teacher_unverified and include_teacher_data)
                    )
                    if training_only and not allowed_training_only:
                        if synthetic:
                            excluded_synthetic += 1
                        else:
                            excluded_training_only += 1
                        continue
                    group = obj.get("training_group")
                    if group is None:
                        if not training_only:
                            group = "public"
                        elif "consensus_category" in obj or "consensus_status" in obj:
                            group = "trusted_consensus"
                        elif human_verified:
                            group = "human_verified"
                        else:
                            group = "ai_unverified"
                    if not isinstance(group, str) or not group.strip() or len(group) > 64:
                        raise ValueError(f"Invalid training_group at line {line_no}")
                    rows.append((str(obj[text_column or "text"]), _label(obj[label_column or "label"]), training_only, synthetic, group))
                except (json.JSONDecodeError, KeyError) as exc:
                    raise ValueError(f"Invalid JSONL record at line {line_no}") from exc
        return rows, excluded_synthetic, excluded_training_only

    with path.open(encoding="utf-8-sig", errors="replace") as handle:
        sample = handle.read(8192)
    if suffix in {".tsv", ".tab"}:
        delimiter = "\t"
    elif suffix == ".csv":
        delimiter = ","
    else:
        first_line = sample.splitlines()[0] if sample.splitlines() else ""
        delimiter = "\t" if "\t" in first_line else ","

    with path.open(encoding="utf-8-sig", errors="replace", newline="") as handle:
        # SMS source rows are delimiter-separated plain text, not CSV quoted
        # records; quotes in the message body must never join multiple lines.
        quote_mode = csv.QUOTE_NONE if delimiter == "\t" else csv.QUOTE_MINIMAL
        reader = csv.reader(handle, delimiter=delimiter, quoting=quote_mode)
        records = list(reader)
    if not records:
        return [], 0, 0
    has_header = text_column is not None or label_column is not None
    if has_header:
        names = [cell.strip() for cell in records[0]]
        try:
            ti = names.index(text_column or "text")
            li = names.index(label_column or "label")
        except ValueError as exc:
            raise ValueError(f"CSV header must contain {text_column or 'text'} and {label_column or 'label'}") from exc
        records = records[1:]
    else:
        ti, li = 1, 0
    output = []
    for row_no, record in enumerate(records, 2 if has_header else 1):
        if len(record) <= max(ti, li):
            raise ValueError(f"Expected text and label columns at row {row_no}")
        output.append((record[ti], _label(record[li]), False, False))
    return output, 0, 0


def load_dataset(
    path: str | Path,
    *,
    text_column: str | None = None,
    label_column: str | None = None,
    include_synthetic: bool = False,
    include_feedback: bool = False,
    include_teacher_data: bool = False,
) -> tuple[SmsDataset, DatasetReport]:
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(source)
    rows, excluded_synthetic, excluded_training_only = _read_rows(
        source,
        text_column,
        label_column,
        include_synthetic=include_synthetic,
        include_feedback=include_feedback,
        include_teacher_data=include_teacher_data,
    )
    return prepare_dataset(rows, excluded_synthetic_rows=excluded_synthetic, excluded_training_only_rows=excluded_training_only)


def merge_datasets(datasets: Iterable[tuple[SmsDataset, DatasetReport]]) -> tuple[SmsDataset, DatasetReport]:
    sources = list(datasets)
    if len(sources) == 1:
        return sources[0]
    rows = [
        (text, label, dataset.training_only[i], dataset.synthetic_flags[i], dataset.supplement_groups[i])
        for dataset, _ in sources
        for i, (text, label) in enumerate(zip(dataset.texts, dataset.labels))
    ]
    merged, report = prepare_dataset(rows, excluded_synthetic_rows=sum(r.excluded_synthetic_rows for _, r in sources))
    return merged, replace(
        report,
        input_rows=sum(r.input_rows for _, r in sources),
        empty_rows=sum(r.empty_rows for _, r in sources),
        exact_duplicates=report.exact_duplicates + sum(r.exact_duplicates for _, r in sources),
        conflicting_template_rows=report.conflicting_template_rows + sum(r.conflicting_template_rows for _, r in sources),
        excluded_training_only_rows=sum(r.excluded_training_only_rows for _, r in sources),
        near_duplicate_template_merges=report.near_duplicate_template_merges,
    )


def prepare_training_data(
    datasets: Iterable[tuple[SmsDataset, DatasetReport]],
    *,
    seed: int = 42,
) -> tuple[SmsDataset, DatasetReport, dict[str, list[int]]]:
    """Split public rows first, then add only non-colliding training-only rows to train."""
    sources = list(datasets)
    public_sources: list[tuple[SmsDataset, DatasetReport]] = []
    training_sources: list[tuple[SmsDataset, DatasetReport]] = []
    for dataset, _ in sources:
        public_rows = [
            (text, label, False, False, "public")
            for i, (text, label) in enumerate(zip(dataset.texts, dataset.labels))
            if not dataset.training_only[i]
        ]
        training_rows = [
            (text, label, True, dataset.synthetic_flags[i], dataset.supplement_groups[i])
            for i, (text, label) in enumerate(zip(dataset.texts, dataset.labels))
            if dataset.training_only[i]
        ]
        if public_rows:
            public_sources.append(prepare_dataset(public_rows))
        if training_rows:
            training_sources.append(prepare_dataset(training_rows))

    public_dataset, public_report = merge_datasets(public_sources) if public_sources else prepare_dataset([])
    training_dataset, training_merge_report = merge_datasets(training_sources) if training_sources else prepare_dataset([])
    public_splits = split_by_template(public_dataset, seed=seed)

    # Build near-duplicate clusters across source boundaries. A synthetic or
    # human-feedback row that resembles any public group is excluded entirely;
    # otherwise adding it could change which public examples land in holdouts.
    overlapping_training_texts: set[str] = set()
    if len(training_dataset):
        cross_source_groups: dict[str, list[tuple[str, str, bool, bool]]] = defaultdict(list)
        for text, label in zip(public_dataset.texts, public_dataset.labels):
            cross_source_groups[normalize_text(text, template=True)].append((text, label, False, False, "public"))
        for i, (text, label) in enumerate(zip(training_dataset.texts, training_dataset.labels)):
            cross_source_groups[normalize_text(text, template=True)].append(
                (text, label, True, training_dataset.synthetic_flags[i], training_dataset.supplement_groups[i])
            )
        cross_source_groups, _ = _merge_near_duplicate_templates(cross_source_groups)
        for rows in cross_source_groups.values():
            if any(not row[2] for row in rows) and any(row[2] for row in rows):
                overlapping_training_texts.update(row[0] for row in rows if row[2])

    retained_training_rows = [
        (text, label, True, training_dataset.synthetic_flags[i], training_dataset.supplement_groups[i])
        for i, (text, label) in enumerate(zip(training_dataset.texts, training_dataset.labels))
        if text not in overlapping_training_texts
    ]
    training_dataset, _ = prepare_dataset(retained_training_rows)
    dataset = SmsDataset(
        texts=public_dataset.texts + training_dataset.texts,
        labels=public_dataset.labels + training_dataset.labels,
        template_ids=public_dataset.template_ids + training_dataset.template_ids,
        training_only=public_dataset.training_only + training_dataset.training_only,
        synthetic_flags=public_dataset.synthetic_flags + training_dataset.synthetic_flags,
        supplement_groups=public_dataset.supplement_groups + training_dataset.supplement_groups,
    )
    train_end = len(public_dataset)
    splits = {
        "train": public_splits["train"] + list(range(train_end, len(dataset))),
        "validation": public_splits["validation"],
        "test": public_splits["test"],
    }

    input_reports = [report for _, report in sources]
    input_synthetic_excluded = sum(report.excluded_synthetic_rows for report in input_reports)
    input_training_excluded = sum(report.excluded_training_only_rows for report in input_reports)
    source_label_counts = Counter(dataset.labels)
    public_source_exact = sum(report.exact_duplicates for _, report in public_sources)
    training_source_exact = sum(report.exact_duplicates for _, report in training_sources)
    public_source_conflicts = sum(report.conflicting_template_rows for _, report in public_sources)
    training_source_conflicts = sum(report.conflicting_template_rows for _, report in training_sources)
    extra_public_exact = max(0, public_report.exact_duplicates - public_source_exact) if len(public_sources) > 1 else 0
    extra_training_exact = max(0, training_merge_report.exact_duplicates - training_source_exact) if len(training_sources) > 1 else 0
    extra_public_conflicts = max(0, public_report.conflicting_template_rows - public_source_conflicts) if len(public_sources) > 1 else 0
    extra_training_conflicts = max(0, training_merge_report.conflicting_template_rows - training_source_conflicts) if len(training_sources) > 1 else 0
    report = DatasetReport(
        input_rows=sum(item.input_rows for item in input_reports),
        kept_rows=len(dataset),
        empty_rows=sum(item.empty_rows for item in input_reports),
        exact_duplicates=sum(item.exact_duplicates for item in input_reports) + extra_public_exact + extra_training_exact,
        conflicting_template_rows=sum(item.conflicting_template_rows for item in input_reports)
        + extra_public_conflicts + extra_training_conflicts,
        label_counts=dict(source_label_counts),
        excluded_synthetic_rows=input_synthetic_excluded,
        included_synthetic_rows=sum(dataset.synthetic_flags),
        excluded_training_only_rows=input_training_excluded + len(overlapping_training_texts),
        excluded_training_only_overlap_rows=len(overlapping_training_texts),
        included_training_only_rows=sum(dataset.training_only),
        near_duplicate_template_merges=public_report.near_duplicate_template_merges
        + training_merge_report.near_duplicate_template_merges,
    )
    return dataset, report, splits


def prepare_dataset(rows: Iterable[tuple], *, excluded_synthetic_rows: int = 0, excluded_training_only_rows: int = 0) -> tuple[SmsDataset, DatasetReport]:
    input_rows = 0
    empty_rows = 0
    exact_duplicates = 0
    deduped: dict[tuple[str, str], tuple[str, str, bool, bool, str]] = {}
    for row in rows:
        input_rows += 1
        if len(row) < 2 or len(row) > 5:
            raise ValueError("dataset rows must contain text, label, and optional training_only/synthetic/group fields")
        text, raw_label = row[:2]
        training_only = bool(row[2]) if len(row) >= 3 else False
        synthetic = bool(row[3]) if len(row) >= 4 else False
        group = str(row[4]) if len(row) >= 5 else ("supplement" if training_only else "public")
        if not group.strip() or len(group) > 64:
            raise ValueError("training group must be a non-empty string of at most 64 characters")
        clean = unicodedata.normalize("NFKC", str(text)).strip()
        if not clean:
            empty_rows += 1
            continue
        label = _label(raw_label)
        key = (_SPACE.sub(" ", clean.casefold()).strip(), label)
        if key in deduped:
            exact_duplicates += 1
            old = deduped[key]
            if old[2] and not training_only:
                deduped[key] = (clean, label, False, False, "public")
            continue
        deduped[key] = (clean, label, training_only, synthetic, group)

    groups: dict[str, list[tuple[str, str, bool, bool, str]]] = defaultdict(list)
    for row in deduped.values():
        groups[normalize_text(row[0], template=True)].append(row)
    groups, near_duplicate_merges = _merge_near_duplicate_templates(groups)
    conflicting = {key for key, group in groups.items() if len({row[1] for row in group}) > 1}
    texts, labels, ids, training_only_flags, synthetic_flags, supplement_groups = [], [], [], [], [], []
    for key, group in groups.items():
        if key in conflicting:
            continue
        for text, label, training_only, synthetic, training_group in group:
            texts.append(text)
            labels.append(label)
            ids.append(hashlib.sha256(key.encode("utf-8")).hexdigest()[:16])
            training_only_flags.append(training_only)
            synthetic_flags.append(synthetic)
            supplement_groups.append(training_group)
    report = DatasetReport(
        input_rows=input_rows,
        kept_rows=len(texts),
        empty_rows=empty_rows,
        exact_duplicates=exact_duplicates,
        conflicting_template_rows=sum(len(groups[key]) for key in conflicting),
        label_counts=dict(Counter(labels)),
        excluded_synthetic_rows=excluded_synthetic_rows,
        included_synthetic_rows=sum(synthetic_flags),
        excluded_training_only_rows=excluded_training_only_rows,
        included_training_only_rows=sum(training_only_flags),
        near_duplicate_template_merges=near_duplicate_merges,
    )
    return SmsDataset(texts, labels, ids, training_only_flags, synthetic_flags, supplement_groups), report


def split_by_template(dataset: SmsDataset, *, seed: int = 42, train: float = 0.70, validation: float = 0.15) -> dict[str, list[int]]:
    """Split public groups first; add supplemental rows only to a matching train group."""
    if train <= 0 or validation <= 0 or train + validation >= 1:
        raise ValueError("train and validation must be positive and sum to less than 1")
    by_label: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    for index, (label, template_id) in enumerate(zip(dataset.labels, dataset.template_ids)):
        by_label[label][template_id].append(index)
    rng = random.Random(seed)
    result = {"train": [], "validation": [], "test": []}
    public_group_count = 0
    for label in sorted(by_label):
        group_ids = [
            group_id for group_id, indices in by_label[label].items()
            if any(not dataset.training_only[i] for i in indices)
        ]
        for group_id, indices in by_label[label].items():
            if group_id not in set(group_ids):
                result["train"].extend(indices)
        if not group_ids:
            continue
        public_group_count += len(group_ids)
        rng.shuffle(group_ids)
        n = len(group_ids)
        if n < 3:
            raise ValueError(f"Need at least 3 distinct template groups for class {label}, got {n}")
        n_train = max(1, min(n - 2, round(n * train)))
        n_val = max(1, min(n - n_train - 1, round(n * validation)))
        partitions = {
            "train": group_ids[:n_train],
            "validation": group_ids[n_train:n_train + n_val],
            "test": group_ids[n_train + n_val:],
        }
        for split_name, split_groups in partitions.items():
            for group_id in split_groups:
                indices = by_label[label][group_id]
                result[split_name].extend(i for i in indices if not dataset.training_only[i])
                if split_name == "train":
                    result["train"].extend(i for i in indices if dataset.training_only[i])
    if public_group_count == 0:
        raise ValueError("At least one non-synthetic, non-training-only dataset is required for validation and test")
    for indices in result.values():
        indices.sort()
    return result


def template_split_report(dataset: SmsDataset, splits: dict[str, list[int]]) -> dict:
    """Summarize template-group counts and prove that supplied splits are disjoint."""
    groups = {
        name: {dataset.template_ids[index] for index in splits.get(name, [])}
        for name in ("train", "validation", "test")
    }
    overlaps = {
        "train_validation": len(groups["train"] & groups["validation"]),
        "train_test": len(groups["train"] & groups["test"]),
        "validation_test": len(groups["validation"] & groups["test"]),
    }
    return {
        "template_groups": {name: len(value) for name, value in groups.items()},
        "overlap_groups": overlaps,
        "disjoint": all(value == 0 for value in overlaps.values()),
    }
