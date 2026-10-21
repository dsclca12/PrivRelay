from __future__ import annotations

import json
import hashlib
import os
import random
import shutil
import time
from collections import Counter
import math
from pathlib import Path

from privatesms.datasets import SmsDataset, split_by_template
from privatesms.inference.transformer import TransformerPredictor
from privatesms.text_normalization import normalize_verification_codes


def _fit_temperature(probabilities, labels: list[str], classes: list[str], *, min_per_class: int = 5) -> dict:
    """Fit one scalar temperature using validation predictions only."""
    import numpy as np
    from scipy.optimize import minimize_scalar
    from scipy.special import logsumexp

    values = np.asarray(probabilities, dtype=float)
    if values.ndim != 2 or values.shape != (len(labels), len(classes)) or not len(labels):
        raise ValueError("calibration probabilities must be a non-empty rows-by-classes matrix")
    if not np.isfinite(values).all() or (values < 0).any() or (values > 1).any():
        raise ValueError("calibration probabilities must be finite values between 0 and 1")
    row_sums = values.sum(axis=1)
    if not np.allclose(row_sums, 1.0, atol=1e-5):
        raise ValueError("calibration probabilities must sum to one for each row")
    label_ids = {label: index for index, label in enumerate(classes)}
    try:
        targets = np.asarray([label_ids[label] for label in labels], dtype=int)
    except KeyError as exc:
        raise ValueError(f"unknown calibration label: {exc.args[0]}") from exc
    support = {label: int(np.sum(targets == index)) for index, label in enumerate(classes)}
    if any(count < min_per_class for count in support.values()):
        return {
            "method": None,
            "temperature": 1.0,
            "confidence_calibrated": False,
            "validation_samples": len(labels),
            "validation_class_support": support,
            "minimum_per_class": min_per_class,
            "reason": "insufficient_validation_support",
        }

    log_probabilities = np.log(np.clip(values, 1e-12, 1.0))

    def negative_log_likelihood(log_temperature: float) -> float:
        scaled = log_probabilities / math.exp(log_temperature)
        return float(np.mean(logsumexp(scaled, axis=1) - scaled[np.arange(len(targets)), targets]))

    result = minimize_scalar(
        negative_log_likelihood,
        method="bounded",
        bounds=(math.log(0.05), math.log(20.0)),
        options={"xatol": 1e-5},
    )
    if not result.success or not math.isfinite(float(result.fun)):
        return {
            "method": None,
            "temperature": 1.0,
            "confidence_calibrated": False,
            "validation_samples": len(labels),
            "validation_class_support": support,
            "minimum_per_class": min_per_class,
            "reason": "temperature_fit_failed",
        }
    nll_before = negative_log_likelihood(0.0)
    nll_after = float(result.fun)
    if nll_after >= nll_before - 1e-6:
        return {
            "method": None,
            "temperature": 1.0,
            "confidence_calibrated": False,
            "validation_samples": len(labels),
            "validation_class_support": support,
            "minimum_per_class": min_per_class,
            "validation_nll_before": nll_before,
            "validation_nll_after": nll_after,
            "reason": "temperature_fit_no_improvement",
        }
    return {
        "method": "temperature_scaling",
        "temperature": math.exp(float(result.x)),
        "confidence_calibrated": True,
        "validation_samples": len(labels),
        "validation_class_support": support,
        "minimum_per_class": min_per_class,
        "validation_nll_before": nll_before,
        "validation_nll_after": nll_after,
        "reason": None,
    }


def _training_fingerprint(
    dataset: SmsDataset,
    splits: dict[str, list[int]],
    *,
    model_name: str,
    classes: list[str],
    seed: int,
    batch_size: int,
    max_length: int,
    learning_rate: float,
    synthetic_loss_share: float | None = None,
    synthetic_loss_shares: dict[str, float] | None = None,
) -> str:
    """Bind checkpoints to the exact local rows, splits, and training configuration."""
    digest = hashlib.sha256()
    config = {
        "model_name": model_name,
        "classes": classes,
        "seed": seed,
        "batch_size": batch_size,
        "max_length": max_length,
        "learning_rate": learning_rate,
        "synthetic_loss_share": synthetic_loss_share,
        "synthetic_loss_shares": synthetic_loss_shares,
        "splits": {name: list(splits[name]) for name in ("train", "validation", "test")},
    }
    digest.update(json.dumps(config, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    for index, (text, label) in enumerate(zip(dataset.texts, dataset.labels)):
        digest.update(index.to_bytes(8, "big"))
        digest.update(label.encode("utf-8"))
        digest.update(b"\0")
        digest.update(b"1" if dataset.training_only[index] else b"0")
        digest.update(b"1" if dataset.synthetic_flags[index] else b"0")
        digest.update(dataset.supplement_groups[index].encode("utf-8"))
        digest.update(b"\0")
        digest.update(text.encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def train_transformer(
    dataset: SmsDataset,
    *,
    model_name: str,
    output_dir: str | Path,
    seed: int = 42,
    epochs: int = 4,
    batch_size: int = 8,
    max_length: int = 128,
    patience: int = 2,
    learning_rate: float = 2e-5,
    num_threads: int = 4,
    resume: bool = False,
    local_files_only: bool = False,
    splits: dict[str, list[int]] | None = None,
    synthetic_loss_share: float | None = None,
    synthetic_loss_shares: dict[str, float] | None = None,
) -> tuple[TransformerPredictor, dict[str, list[int]], dict]:
    """CPU-only, resumable fine tuning; never reads anything except the supplied local dataset."""
    try:
        import numpy as np
        import torch
        from sklearn.metrics import f1_score
        from torch.utils.data import DataLoader, Dataset
        from transformers import AutoModelForSequenceClassification, AutoTokenizer
    except ImportError as exc:
        raise RuntimeError("Install CPU PyTorch and Transformers with `pip install -e '.[transformer]'`") from exc
    if epochs < 1 or batch_size < 1 or max_length < 8 or patience < 1 or num_threads < 1:
        raise ValueError("epochs, batch_size, patience, num_threads must be positive and max_length must be >= 8")
    if len(set(dataset.labels)) < 2:
        raise ValueError("Transformer fine tuning requires at least two classes")

    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.set_num_threads(num_threads)
    device = torch.device("cpu")
    classes = sorted(set(dataset.labels))
    label_to_id = {label: i for i, label in enumerate(classes)}
    splits = splits or split_by_template(dataset, seed=seed)
    if set(splits) != {"train", "validation", "test"}:
        raise ValueError("splits must contain exactly train, validation, and test")
    if not splits["train"] or not splits["validation"]:
        raise ValueError("Transformer training requires non-empty train and validation splits")
    all_indices = [index for name in ("train", "validation", "test") for index in splits[name]]
    if any(index < 0 or index >= len(dataset) for index in all_indices) or len(all_indices) != len(set(all_indices)):
        raise ValueError("splits contain out-of-range or overlapping row indices")
    train_indices = splits["train"]
    train_label_counts = Counter(dataset.labels[i] for i in train_indices)
    supplement_group_label_counts = Counter(
        (dataset.supplement_groups[i], dataset.labels[i])
        for i in train_indices
        if dataset.training_only[i] or dataset.synthetic_flags[i]
    )
    supplement_groups = {group for group, _ in supplement_group_label_counts}
    if synthetic_loss_share is not None and synthetic_loss_shares is not None:
        raise ValueError("Use either synthetic_loss_share or synthetic_loss_shares, not both")
    resolved_shares = None
    if synthetic_loss_share is not None:
        if not 0 < synthetic_loss_share < 1:
            raise ValueError("synthetic_loss_share must be between 0 and 1, exclusive")
        resolved_shares = {group: synthetic_loss_share for group in supplement_groups}
    elif synthetic_loss_shares is not None:
        resolved_shares = dict(synthetic_loss_shares)
        if set(resolved_shares) != supplement_groups:
            missing = sorted(supplement_groups - set(resolved_shares))
            unknown = sorted(set(resolved_shares) - supplement_groups)
            raise ValueError(f"Synthetic loss shares must cover exactly the supplement groups; missing={missing}, unknown={unknown}")
        if any(not 0 < value < 1 for value in resolved_shares.values()):
            raise ValueError("each synthetic loss share must be between 0 and 1, exclusive")
    if resolved_shares is not None:
        supplement_label_counts = Counter(
            dataset.labels[i]
            for i in train_indices
            if dataset.training_only[i] or dataset.synthetic_flags[i]
        )
        missing_public_classes = sorted(
            label for label in supplement_label_counts
            if train_label_counts[label] <= supplement_label_counts[label]
        )
        if missing_public_classes:
            raise ValueError(
                "Per-class synthetic loss weighting requires a public training example for every supplemental label; "
                f"missing {missing_public_classes}"
            )
        public_label_counts = {
            label: train_label_counts[label] - supplement_label_counts[label]
            for label in train_label_counts
        }
        supplement_weights = {
            (group, label): (resolved_shares[group] / (1 - resolved_shares[group]))
            * public_label_counts[label] / count
            for (group, label), count in supplement_group_label_counts.items()
        }
        row_loss_weights = [
            supplement_weights[(dataset.supplement_groups[index], dataset.labels[index])]
            if dataset.training_only[index] or dataset.synthetic_flags[index]
            else 1.0
            for index in train_indices
        ]
    else:
        row_loss_weights = [1.0] * len(train_indices)

    fingerprint = _training_fingerprint(
        dataset, splits, model_name=model_name, classes=classes, seed=seed,
        batch_size=batch_size, max_length=max_length, learning_rate=learning_rate,
        synthetic_loss_share=synthetic_loss_share,
        synthetic_loss_shares=resolved_shares,
    )
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    best_dir = output / "best_model"
    checkpoint_path = output / "training-checkpoint.pt"
    tokenizer = AutoTokenizer.from_pretrained(model_name, local_files_only=local_files_only)
    model = AutoModelForSequenceClassification.from_pretrained(
        model_name,
        num_labels=len(classes),
        id2label={i: label for i, label in enumerate(classes)},
        label2id=label_to_id,
        ignore_mismatched_sizes=True,
        local_files_only=local_files_only,
    ).to(device)

    class SmsRows(Dataset):
        def __init__(self, indices: list[int], weights: list[float] | None = None):
            self.indices = indices
            self.weights = weights

        def __len__(self):
            return len(self.indices)

        def __getitem__(self, index):
            row_index = self.indices[index]
            encoded = tokenizer(normalize_verification_codes(dataset.texts[row_index]), truncation=True, max_length=max_length, padding=False)
            encoded["labels"] = label_to_id[dataset.labels[row_index]]
            if self.weights is not None:
                encoded["sample_weight"] = self.weights[index]
            return encoded

    def collate(rows):
        labels = torch.tensor([row.pop("labels") for row in rows], dtype=torch.long)
        sample_weights = torch.tensor([row.pop("sample_weight", 1.0) for row in rows], dtype=torch.float32)
        batch = tokenizer.pad(rows, padding=True, return_tensors="pt")
        batch["labels"] = labels
        batch["sample_weights"] = sample_weights
        return batch

    train_indices = splits["train"]
    label_counts = Counter(dataset.labels[i] for i in train_indices)
    class_loss_weights = torch.tensor([len(train_indices) / (len(classes) * label_counts[label]) for label in classes], dtype=torch.float32, device=device)
    train_loader = DataLoader(SmsRows(train_indices, row_loss_weights), batch_size=batch_size, shuffle=True, collate_fn=collate, num_workers=0)
    validation_loader = DataLoader(SmsRows(splits["validation"]), batch_size=batch_size, shuffle=False, collate_fn=collate, num_workers=0)
    optimizer = torch.optim.AdamW(model.parameters(), lr=learning_rate)
    start_epoch, best_f1, bad_epochs = 0, -1.0, 0
    if resume and not checkpoint_path.exists():
        raise FileNotFoundError(f"Cannot resume: checkpoint does not exist: {checkpoint_path}")
    if resume:
        state = torch.load(checkpoint_path, map_location="cpu", weights_only=False)
        if state.get("training_fingerprint") != fingerprint:
            raise ValueError("Resume checkpoint data, splits, or training configuration does not match")
        if not best_dir.is_dir():
            raise ValueError("Resume checkpoint exists but the best_model directory is missing")
        model.load_state_dict(state["model"])
        optimizer.load_state_dict(state["optimizer"])
        start_epoch = state["epoch"] + 1
        best_f1 = state["best_macro_f1"]
        bad_epochs = state["bad_epochs"]
        torch.set_rng_state(state["torch_rng_state"])
        random.setstate(state["python_rng_state"])

    history = []
    best_model = None
    for epoch in range(start_epoch, epochs):
        epoch_start = time.perf_counter()
        model.train()
        loss_sum, seen = 0.0, 0
        for batch in train_loader:
            labels = batch.pop("labels").to(device)
            sample_weights = batch.pop("sample_weights").to(device)
            batch = {key: value.to(device) for key, value in batch.items()}
            optimizer.zero_grad(set_to_none=True)
            logits = model(**batch).logits
            per_row_loss = torch.nn.functional.cross_entropy(logits, labels, weight=class_loss_weights, reduction="none")
            effective_weights = class_loss_weights[labels] * sample_weights
            loss = (per_row_loss * sample_weights).sum() / effective_weights.sum().clamp_min(1e-12)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            loss_sum += float(loss.item()) * len(labels)
            seen += len(labels)

        model.eval()
        gold, predicted = [], []
        with torch.inference_mode():
            for batch in validation_loader:
                labels = batch.pop("labels")
                batch = {key: value.to(device) for key, value in batch.items()}
                predicted.extend(model(**batch).logits.argmax(dim=-1).cpu().tolist())
                gold.extend(labels.tolist())
        val_f1 = float(f1_score(gold, predicted, labels=list(range(len(classes))), average="macro", zero_division=0))
        history.append({"epoch": epoch + 1, "train_loss": loss_sum / max(1, seen), "validation_macro_f1": val_f1, "seconds": time.perf_counter() - epoch_start})
        if val_f1 > best_f1:
            best_f1 = val_f1
            bad_epochs = 0
            temporary_best = output / "best_model.tmp"
            if temporary_best.exists():
                shutil.rmtree(temporary_best)
            model.save_pretrained(temporary_best)
            tokenizer.save_pretrained(temporary_best)
            if best_dir.exists():
                shutil.rmtree(best_dir)
            os.replace(temporary_best, best_dir)
        else:
            bad_epochs += 1

        temporary_checkpoint = checkpoint_path.with_suffix(".pt.tmp")
        torch.save({
            "model_name": model_name,
            "classes": classes,
            "training_fingerprint": fingerprint,
            "epoch": epoch,
            "model": model.state_dict(),
            "optimizer": optimizer.state_dict(),
            "best_macro_f1": best_f1,
            "bad_epochs": bad_epochs,
            "torch_rng_state": torch.get_rng_state(),
            "python_rng_state": random.getstate(),
        }, temporary_checkpoint)
        os.replace(temporary_checkpoint, checkpoint_path)
        if bad_epochs >= patience:
            break

    if not best_dir.exists():
        raise RuntimeError("No best checkpoint was written; check that validation data contains examples")
    best_model = AutoModelForSequenceClassification.from_pretrained(best_dir, local_files_only=True).to(device)
    best_tokenizer = AutoTokenizer.from_pretrained(best_dir, local_files_only=True)
    raw_predictor = TransformerPredictor(model=best_model, tokenizer=best_tokenizer, classes=classes, max_length=max_length, batch_size=batch_size)
    validation_texts = [dataset.texts[i] for i in splits["validation"]]
    validation_labels = [dataset.labels[i] for i in splits["validation"]]
    calibration = _fit_temperature(raw_predictor.predict_proba(validation_texts), validation_labels, classes)
    raw_predictor.temperature = calibration["temperature"]
    predictor = raw_predictor
    metadata = {
        "version": "transformer-" + model_name.replace("/", "-") + "-v1",
        "model_name": model_name,
        "classes": classes,
        "max_length": max_length,
        "decision_threshold": 0.5,
        "review_confidence_threshold": 0.6,
        "confidence_calibrated": calibration["confidence_calibrated"],
        "calibration_method": calibration["method"],
        "calibration_temperature": calibration["temperature"],
        "confidence_calibration": calibration,
        "best_validation_macro_f1": best_f1,
        "seed": seed,
        "device": "cpu",
        "history": history,
        "synthetic_loss_share_per_class": synthetic_loss_share,
        "synthetic_loss_shares_by_group": resolved_shares,
        "training_weight_policy": "per-group-supplement-to-public-loss-ratio-per-class" if synthetic_loss_shares is not None else "equal-effective-supplement-loss-share-per-class" if synthetic_loss_share is not None else "default-unweighted-samples",
        "training_group_weight_semantics": (
            "Each group target share is defined relative to public loss; group supplement contributions are added and then globally normalized."
            if synthetic_loss_shares is not None else None
        ),
    }
    (output / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return predictor, splits, metadata
