from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import sys
import time
from pathlib import Path
from urllib.request import urlretrieve

import joblib
from privatesms.datasets import import_fgrc_scd_sms, load_dataset, merge_datasets, prepare_training_data, sanitize_public_dataset, template_split_report
from privatesms.evaluation import choose_threshold, evaluate
from privatesms.inference import load_model, predict
from privatesms.generators import generate_synthetic
from privatesms.generators.synthetic import GenerationError
from privatesms.labeling import label_public_dataset, review_teacher_suggestions
from privatesms.feedback import FeedbackStore
from privatesms.inference.registry import ModelRegistry, artifact_sha256
from privatesms.training import train_baseline, train_transformer


PUBLIC_SOURCES = {
    "spam-messages-lr": "https://raw.githubusercontent.com/x-hacker/SpamMessagesLR/master/train.txt",
}


def _write_json(path: str | Path, value: dict) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _ensure_report_outside_artifact(report: str | Path, artifact: str | Path) -> None:
    report_path = Path(report).expanduser().resolve()
    artifact_path = Path(artifact).expanduser().resolve()
    if artifact_path.is_dir():
        try:
            report_path.relative_to(artifact_path)
        except ValueError:
            return
        raise ValueError("evaluation report must be stored outside the candidate artifact directory")
    if report_path == artifact_path:
        raise ValueError("evaluation report cannot overwrite the candidate model artifact")


def _write_private_json(path: str | Path, value: dict) -> str:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    descriptor = os.open(target, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(target, 0o600)
    return hashlib.sha256(payload).hexdigest()


def _test_policy(dataset, indices: list[int]) -> dict:
    return {
        "training_only_rows": sum(dataset.training_only[i] for i in indices),
        "synthetic_rows": sum(dataset.synthetic_flags[i] for i in indices),
        "samples": len(indices),
    }


def _cpu_model_name() -> str:
    try:
        for line in Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="replace").splitlines():
            key, separator, value = line.partition(":")
            if separator and key.strip().casefold() in {"model name", "hardware"} and value.strip():
                return value.strip()
    except OSError:
        pass
    return platform.processor() or platform.machine()


def _registry_version_for_artifact(model_path: str | Path) -> str | None:
    resolved = Path(model_path).resolve()
    for parent in resolved.parents:
        if parent.parent.name == "versions":
            return parent.name
    return None


def main() -> None:
    parser = argparse.ArgumentParser(prog="privatesms")
    commands = parser.add_subparsers(dest="command", required=True)
    download = commands.add_parser("download-public", help="Download one named public source to a local path")
    download.add_argument("--source", choices=PUBLIC_SOURCES, required=True)
    download.add_argument("--output", required=True)

    sanitize = commands.add_parser("sanitize-public", help="Redact common identifiers in a confirmed public source locally")
    sanitize.add_argument("--input", required=True, help="Source file under data/raw/")
    sanitize.add_argument("--output", required=True, help="New JSONL file under data/processed/")
    sanitize.add_argument("--confirm-public-source", action="store_true", help="Confirm this source is public and permitted for local processing")

    fgrc = commands.add_parser("import-fgrc-scd-sms", help="Import a capped, training-only subset of the synthetic FGRC-SCD SMS corpus")
    fgrc.add_argument("--input", default="data/raw/fgrc-scd-sms.zip")
    fgrc.add_argument("--output", default="data/processed/fgrc-scd-sms-training.jsonl")
    fgrc.add_argument("--max-per-class", type=int, default=250)
    fgrc.add_argument("--seed", type=int, default=42)
    fgrc.add_argument("--risk-only-as-suspicious", action="store_true", help="Keep only source-labeled fraud messages mapped to suspicious; still synthetic and training-only")

    train = commands.add_parser("train", help="Train and evaluate the Phase 1 baseline")
    train.add_argument("--input", action="append", required=True, help="Input path; may be repeated to combine sources")
    train.add_argument("--text-column")
    train.add_argument("--label-column")
    train.add_argument("--model", default="artifacts/baseline.joblib")
    train.add_argument("--report", default="artifacts/evaluation.json")
    train.add_argument("--ham-fpr-limit", type=float, default=0.005, help="Maximum benign false-positive rate on validation (default 0.5%% for margin)")
    train.add_argument("--seed", type=int, default=42)
    train.add_argument("--include-synthetic", action="store_true", help="Include teacher-generated, unverified JSONL records")
    train.add_argument("--include-feedback", action="store_true", help="Include human corrections; they remain train-only and are not used for validation/test")
    train.add_argument("--max-synthetic-fraction", type=float, default=0.25)
    train.add_argument(
        "--synthetic-loss-share",
        type=float,
        help="Set the synthetic/training-only loss share within each class (0 < value < 1); opt-in",
    )

    transformer = commands.add_parser("train-transformer", help="Optional CPU-only Transformer fine tuning")
    transformer.add_argument("--input", action="append", required=True)
    transformer.add_argument("--text-column")
    transformer.add_argument("--label-column")
    transformer.add_argument("--output", default="artifacts/rbt3")
    transformer.add_argument("--report", default="artifacts/rbt3-evaluation.json")
    transformer.add_argument("--model-name", default="hfl/rbt3")
    transformer.add_argument("--seed", type=int, default=42)
    transformer.add_argument("--epochs", type=int, default=4)
    transformer.add_argument("--batch-size", type=int, default=8)
    transformer.add_argument("--max-length", type=int, default=128)
    transformer.add_argument("--patience", type=int, default=2)
    transformer.add_argument("--num-threads", type=int, default=16)
    transformer.add_argument("--resume", action="store_true")
    transformer.add_argument("--local-files-only", action="store_true")
    transformer.add_argument("--ham-fpr-limit", type=float, default=0.005)
    transformer.add_argument("--include-synthetic", action="store_true")
    transformer.add_argument("--include-feedback", action="store_true")
    transformer.add_argument("--max-synthetic-fraction", type=float, default=0.25)
    transformer.add_argument("--synthetic-loss-share", type=float)
    transformer.add_argument(
        "--supplement-loss-share",
        action="append",
        default=[],
        metavar="GROUP=SHARE",
        help="Set this group's supplement-to-public loss share per class; group contributions add before normalization",
    )

    onnx_cmd = commands.add_parser("export-onnx", help="Export and benchmark float/INT8 ONNX on a separate local evaluation set")
    onnx_cmd.add_argument("--model-dir", required=True)
    onnx_cmd.add_argument("--output-dir", default="artifacts/onnx")
    onnx_cmd.add_argument("--input", action="append", required=True)
    onnx_cmd.add_argument("--validation-input", action="append", required=True)
    onnx_cmd.add_argument("--text-column")
    onnx_cmd.add_argument("--label-column")
    onnx_cmd.add_argument("--threads", type=int, default=16)
    onnx_cmd.add_argument("--ham-fpr-limit", type=float, default=0.005)
    onnx_cmd.add_argument("--latency-samples", type=int, default=128)
    onnx_cmd.add_argument("--report", default="artifacts/onnx-benchmark.json")
    onnx_cmd.add_argument("--no-quantize", action="store_true")

    evaluate_cmd = commands.add_parser("evaluate", help="Evaluate a saved model on a separate local dataset")
    evaluate_cmd.add_argument("--model", required=True)
    evaluate_cmd.add_argument("--input", action="append", required=True)
    evaluate_cmd.add_argument("--text-column")
    evaluate_cmd.add_argument("--label-column")
    evaluate_cmd.add_argument("--threshold", type=float)
    evaluate_cmd.add_argument("--report", default="artifacts/evaluation.json")

    benchmark = commands.add_parser("benchmark", help="Measure a saved model on a local held-out dataset")
    benchmark.add_argument("--model", required=True)
    benchmark.add_argument("--input", action="append", required=True)
    benchmark.add_argument("--text-column")
    benchmark.add_argument("--label-column")
    benchmark.add_argument("--threshold", type=float)
    benchmark.add_argument("--threads", type=int, default=1)
    benchmark.add_argument("--latency-samples", type=int, default=128)
    benchmark.add_argument("--report", default="artifacts/benchmark.json")

    inference = commands.add_parser("predict", help="Classify one local text without logging its content")
    inference.add_argument("--model", required=True)
    inference.add_argument("--text", required=True)
    inference.add_argument("--threshold", type=float)

    synthetic = commands.add_parser("generate-synthetic", help="Opt-in synthetic generation; default performs no API requests")
    synthetic.add_argument("--count", type=int, default=0, help="Number of samples (0 performs no calls; max 10 per run)")
    synthetic.add_argument("--output", default="data/raw/synthetic_teacher.jsonl")
    synthetic.add_argument("--max-cost-usd", type=float, default=0.0)
    synthetic.add_argument("--allow-remote-generation", action="store_true")

    assisted = commands.add_parser("label-public", help="Create budget-capped teacher label suggestions for explicit public data")
    assisted.add_argument("--input", required=True, help="Public source file under data/raw/ only")
    assisted.add_argument("--output", default="data/processed/teacher-assisted.jsonl")
    assisted.add_argument("--count", type=int, required=True, help="Rows to label from the beginning of the source (max 10 per run)")
    assisted.add_argument("--max-cost-usd", type=float, default=0.0)
    assisted.add_argument("--allow-remote-labeling", action="store_true")
    assisted.add_argument("--confirm-public-data-egress", action="store_true", help="Confirm the source is public and permitted to send to the configured teacher")

    review_labels = commands.add_parser("review-teacher-labels", help="Review teacher label suggestions locally before training")
    review_labels.add_argument("--input", required=True, help="Teacher suggestions under data/processed/")
    review_labels.add_argument("--output", default="data/processed/teacher-reviewed.jsonl")
    review_labels.add_argument("--max-records", type=int, default=100)

    feedback_export = commands.add_parser("feedback-export", help="Export only human-approved local corrections as JSONL")
    feedback_export.add_argument("--database", default="data/feedback.sqlite3")
    feedback_export.add_argument("--output", default="data/processed/feedback-approved.jsonl")

    registry_common = argparse.ArgumentParser(add_help=False)
    registry_common.add_argument("--registry", default="artifacts/model_registry")
    register = commands.add_parser("model-register", parents=[registry_common], help="Copy a local model artifact into immutable version storage")
    register.add_argument("--candidate", required=True)
    register.add_argument("--version", required=True)
    activate = commands.add_parser("model-activate", parents=[registry_common], help="Activate only after an independent test report meets the FPR gate")
    activate.add_argument("--version", required=True)
    activate.add_argument("--evaluation", required=True)
    activate.add_argument("--max-risk-fpr", type=float, default=0.01)
    commands.add_parser("model-rollback", parents=[registry_common], help="Atomically switch to the previous model version")
    commands.add_parser("model-current", parents=[registry_common], help="Show the active and previous local model versions")

    args = parser.parse_args()
    if args.command == "import-fgrc-scd-sms":
        try:
            result = import_fgrc_scd_sms(
                args.input,
                args.output,
                max_per_class=args.max_per_class,
                seed=args.seed,
                risk_only_as_suspicious=args.risk_only_as_suspicious,
            )
        except (ValueError, FileNotFoundError, FileExistsError) as exc:
            parser.error(str(exc))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    if args.command == "sanitize-public":
        try:
            result = sanitize_public_dataset(
                args.input,
                args.output,
                confirm_public_source=args.confirm_public_source,
            )
        except (ValueError, FileNotFoundError, FileExistsError) as exc:
            parser.error(str(exc))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    if args.command == "generate-synthetic":
        if args.count == 0:
            print(json.dumps({"requested": 0, "api_calls": 0, "total_cost_usd": 0.0}, ensure_ascii=False))
            return
        try:
            result = generate_synthetic(
                count=args.count,
                output=args.output,
                max_cost_usd=args.max_cost_usd,
                allow_remote=args.allow_remote_generation,
                env_allow=os.getenv("PRIVATESMS_ALLOW_SYNTHETIC_API") == "1",
            )
        except GenerationError as exc:
            parser.error(str(exc))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    if args.command == "label-public":
        source = Path(args.input).resolve()
        public_root = Path("data/raw").resolve()
        output = Path(args.output).resolve()
        processed_root = Path("data/processed").resolve()
        try:
            source.relative_to(public_root)
            output.relative_to(processed_root)
        except ValueError:
            parser.error("--input must be under data/raw and --output must be under data/processed")
        try:
            result = label_public_dataset(
                input_path=source,
                output_path=output,
                count=args.count,
                max_cost_usd=args.max_cost_usd,
                allow_remote=args.allow_remote_labeling,
                env_allow=os.getenv("PRIVATESMS_ALLOW_PUBLIC_LABELING_API") == "1",
                confirm_public_egress=args.confirm_public_data_egress,
            )
        except GenerationError as exc:
            parser.error(str(exc))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    if args.command == "review-teacher-labels":
        source = Path(args.input).resolve()
        output = Path(args.output).resolve()
        processed_root = Path("data/processed").resolve()
        try:
            source.relative_to(processed_root)
            output.relative_to(processed_root)
        except ValueError:
            parser.error("--input and --output must be under data/processed")

        def request_human_label(record: dict, index: int) -> str | None:
            confidence = record.get("teacher_confidence")
            suggestion = record.get("category", "unknown")
            print(f"\n[{index + 1}] 教师建议={suggestion}，教师置信度={confidence}")
            print(record.get("text", ""))
            answer = input("人工类别 (personal/otp/service/transaction/marketing/suspicious/uncertain；回车跳过): ")
            return answer.strip() or None

        try:
            result = review_teacher_suggestions(
                input_path=source,
                output_path=output,
                decision_provider=request_human_label,
                max_records=args.max_records,
            )
        except (ValueError, FileNotFoundError) as exc:
            parser.error(str(exc))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    if args.command == "feedback-export":
        count = FeedbackStore(args.database).export_approved(args.output)
        print(json.dumps({"approved_samples_exported": count, "output": args.output}, ensure_ascii=False))
        return
    if args.command.startswith("model-"):
        registry = ModelRegistry(args.registry)
        try:
            if args.command == "model-register":
                result = registry.register(args.candidate, args.version)
            elif args.command == "model-activate":
                result = str(registry.activate(args.version, evaluation_report=args.evaluation, max_risk_fpr=args.max_risk_fpr))
            elif args.command == "model-rollback":
                result = str(registry.rollback())
            else:
                result = registry.current()
        except (ValueError, FileExistsError, FileNotFoundError) as exc:
            parser.error(str(exc))
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return
    if args.command == "download-public":
        target = Path(args.output)
        target.parent.mkdir(parents=True, exist_ok=True)
        urlretrieve(PUBLIC_SOURCES[args.source], target)
        print(f"Downloaded public source to {target}. Check upstream terms before redistribution.")
        return
    if args.command == "predict":
        print(json.dumps(predict(load_model(args.model), args.text, threshold=args.threshold), ensure_ascii=False))
        return
    if args.command == "evaluate":
        sources = [load_dataset(path, text_column=args.text_column, label_column=args.label_column) for path in args.input]
        dataset, data_report = merge_datasets(sources)
        bundle = load_model(args.model)
        _ensure_report_outside_artifact(args.report, args.model)
        threshold = bundle.get("decision_threshold", 0.5) if args.threshold is None else args.threshold
        report = {"data": data_report.__dict__, "model_classes": bundle.get("classes", list(bundle["model"].classes_)), "test_data_policy": _test_policy(dataset, list(range(len(dataset)))), "test": evaluate(bundle["model"], dataset.texts, dataset.labels, threshold=threshold, category_decision=bundle.get("category_decision", "risk_threshold")), "candidate_artifact_sha256": artifact_sha256(args.model)}
        _write_json(args.report, report)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return
    if args.command == "benchmark":
        if args.threads < 1 or args.latency_samples < 1:
            parser.error("--threads and --latency-samples must be positive")
        from privatesms.evaluation.onnx_benchmark import benchmark_predictor
        from threadpoolctl import threadpool_limits

        sources = [load_dataset(path, text_column=args.text_column, label_column=args.label_column) for path in args.input]
        dataset, data_report = merge_datasets(sources)
        if not dataset.texts:
            parser.error("benchmark dataset has no usable public, non-training-only rows")
        load_started = time.perf_counter()
        benchmark_model_path = Path(args.model)
        if benchmark_model_path.is_dir() and (benchmark_model_path / "model.onnx").is_file():
            from privatesms.inference.onnx import load_onnx_bundle

            bundle = load_onnx_bundle(benchmark_model_path, threads=args.threads)
        else:
            if benchmark_model_path.is_dir():
                try:
                    import torch

                    torch.set_num_threads(args.threads)
                except ImportError:
                    pass
            bundle = load_model(args.model)
        model_load_ms = (time.perf_counter() - load_started) * 1000
        threshold = bundle.get("decision_threshold", 0.5) if args.threshold is None else args.threshold
        with threadpool_limits(limits=args.threads):
            measurements = benchmark_predictor(
                bundle["model"], dataset.texts, dataset.labels,
                threshold=threshold,
                model_path=args.model,
                latency_limit=args.latency_samples,
                category_decision=bundle.get("category_decision", "risk_threshold"),
            )
        report = {
            "data": data_report.__dict__,
            "test_data_policy": _test_policy(dataset, list(range(len(dataset)))),
            "model_classes": bundle["classes"] if "classes" in bundle else list(bundle["model"].classes_),
            "model_version": _registry_version_for_artifact(args.model) or bundle.get("version", "unknown"),
            "decision_threshold": threshold,
            "model_load_ms": model_load_ms,
            "threads": args.threads,
            "runtime": {
                "os": platform.platform(),
                "python": sys.version.split()[0],
                "processor": _cpu_model_name(),
                "cpu_count": os.cpu_count(),
            },
            **measurements,
        }
        _write_json(args.report, report)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return

    include_synthetic = getattr(args, "include_synthetic", False)
    include_feedback = getattr(args, "include_feedback", False)
    sources = [load_dataset(path, text_column=args.text_column, label_column=args.label_column, include_synthetic=include_synthetic, include_feedback=include_feedback) for path in args.input]
    dataset, data_report, training_splits = prepare_training_data(sources, seed=args.seed)
    max_synthetic_fraction = getattr(args, "max_synthetic_fraction", 0.25)
    if not 0 <= max_synthetic_fraction <= 1:
        parser.error("--max-synthetic-fraction must be between 0 and 1")
    if getattr(args, "include_synthetic", False) and data_report.input_rows and data_report.included_synthetic_rows / data_report.input_rows > max_synthetic_fraction:
        parser.error("Synthetic data exceeds --max-synthetic-fraction; review the source mix explicitly")
    synthetic_loss_share = getattr(args, "synthetic_loss_share", None)
    if synthetic_loss_share is not None and not 0 < synthetic_loss_share < 1:
        parser.error("--synthetic-loss-share must be greater than 0 and less than 1")
    if synthetic_loss_share is not None and not (data_report.included_synthetic_rows or data_report.included_training_only_rows):
        parser.error("--synthetic-loss-share requires included synthetic or training-only rows")
    supplement_loss_shares = {}
    for item in getattr(args, "supplement_loss_share", []):
        group, separator, value = item.partition("=")
        if not separator or not group.strip():
            parser.error("--supplement-loss-share must use GROUP=SHARE")
        if group in supplement_loss_shares:
            parser.error(f"duplicate --supplement-loss-share group: {group}")
        try:
            share = float(value)
        except ValueError:
            parser.error(f"invalid --supplement-loss-share value for {group}: {value}")
        if not 0 < share < 1:
            parser.error(f"--supplement-loss-share for {group} must be greater than 0 and less than 1")
        supplement_loss_shares[group] = share
    if supplement_loss_shares and synthetic_loss_share is not None:
        parser.error("Use --supplement-loss-share or --synthetic-loss-share, not both")
    if supplement_loss_shares:
        actual_groups = {
            dataset.supplement_groups[index]
            for index in range(len(dataset))
            if dataset.training_only[index] or dataset.synthetic_flags[index]
        }
        if set(supplement_loss_shares) != actual_groups:
            parser.error(
                "--supplement-loss-share groups must cover all included supplements exactly; "
                f"actual={sorted(actual_groups)} configured={sorted(supplement_loss_shares)}"
            )

    if args.command == "train-transformer":
        _ensure_report_outside_artifact(args.report, args.output)
        predictor, splits, metadata = train_transformer(
            dataset,
            model_name=args.model_name,
            output_dir=args.output,
            seed=args.seed,
            epochs=args.epochs,
            batch_size=args.batch_size,
            max_length=args.max_length,
            patience=args.patience,
            num_threads=args.num_threads,
            resume=args.resume,
            local_files_only=args.local_files_only,
            splits=training_splits,
            synthetic_loss_share=synthetic_loss_share,
            synthetic_loss_shares=supplement_loss_shares or None,
        )
        validation = splits["validation"]
        selected = choose_threshold(predictor, [dataset.texts[i] for i in validation], [dataset.labels[i] for i in validation], ham_fpr_limit=args.ham_fpr_limit)
        metadata["decision_threshold"] = selected["threshold"]
        output_dir = Path(args.output)
        template_manifest = {
            "schema_version": 1,
            "template_ids": sorted({dataset.template_ids[i] for i in splits["train"]}),
        }
        metadata["training_template_manifest_sha256"] = _write_private_json(
            output_dir / "training-template-ids.json", template_manifest
        )
        metadata["training_template_manifest"] = "training-template-ids.json"
        isolation_report = template_split_report(dataset, splits)
        if not isolation_report["disjoint"]:
            parser.error("training split contains overlapping template groups")
        (output_dir / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        test_indices = splits["test"]
        report = {
            "data": data_report.__dict__,
            "split_sizes": {name: len(indices) for name, indices in splits.items()},
            "template_split_isolation": isolation_report,
            "test_data_policy": _test_policy(dataset, test_indices),
            "model_classes": metadata["classes"],
            "validation_threshold_selection": selected,
            "confidence_calibration": metadata["confidence_calibration"],
            "training_weight_policy": metadata["training_weight_policy"],
            "synthetic_loss_share_per_class": metadata["synthetic_loss_share_per_class"],
            "synthetic_loss_shares_by_group": metadata["synthetic_loss_shares_by_group"],
            "training_group_weight_semantics": metadata["training_group_weight_semantics"],
            "test": evaluate(predictor, [dataset.texts[i] for i in test_indices], [dataset.labels[i] for i in test_indices], threshold=selected["threshold"], sample_ids=test_indices),
            "model_version": metadata["version"],
            "candidate_artifact_sha256": artifact_sha256(output_dir),
        }
        _write_json(args.report, report)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return

    if args.command == "export-onnx":
        _ensure_report_outside_artifact(args.report, args.output_dir)
        try:
            from privatesms.evaluation.onnx_benchmark import benchmark_predictor
            from privatesms.inference.onnx import load_onnx_bundle
            from privatesms.inference.onnx_export import export_transformer_onnx
        except ImportError as exc:
            parser.error("Install optional dependencies with `pip install -e '.[transformer,onnx]'`")
        if args.threads < 1 or args.latency_samples < 1:
            parser.error("--threads and --latency-samples must be positive")
        if not 0 <= args.ham_fpr_limit <= 1:
            parser.error("--ham-fpr-limit must be between 0 and 1")
        try:
            validation_sources = [
                load_dataset(path, text_column=args.text_column, label_column=args.label_column)
                for path in args.validation_input
            ]
            validation_dataset, validation_report = merge_datasets(validation_sources)
        except (OSError, ValueError) as exc:
            parser.error(f"Could not load ONNX validation dataset: {exc}")
        if validation_report.included_synthetic_rows or validation_report.included_training_only_rows:
            parser.error("ONNX validation data must contain only public non-synthetic, non-training-only rows")
        if set(dataset.template_ids) & set(validation_dataset.template_ids):
            parser.error("ONNX validation and test data share template groups")
        model_dir = Path(args.model_dir)
        template_manifest_path = model_dir / "training-template-ids.json"
        model_metadata_path = model_dir / "metadata.json"
        if not template_manifest_path.is_file() or not model_metadata_path.is_file():
            parser.error("Transformer model is missing its training template manifest; retrain it with this CLI before export")
        template_manifest_bytes = template_manifest_path.read_bytes()
        source_metadata = json.loads(model_metadata_path.read_text(encoding="utf-8"))
        manifest_sha256 = hashlib.sha256(template_manifest_bytes).hexdigest()
        if source_metadata.get("training_template_manifest_sha256") != manifest_sha256:
            parser.error("training template manifest hash does not match model metadata")
        template_manifest = json.loads(template_manifest_bytes)
        training_template_ids = set(template_manifest.get("template_ids", []))
        validation_overlap = len(training_template_ids & set(validation_dataset.template_ids))
        test_overlap = len(training_template_ids & set(dataset.template_ids))
        template_isolation = {
            "training_template_manifest_sha256": manifest_sha256,
            "training_template_groups": len(training_template_ids),
            "validation_template_groups": len(set(validation_dataset.template_ids)),
            "test_template_groups": len(set(dataset.template_ids)),
            "overlap_groups": {
                "train_validation": validation_overlap,
                "train_test": test_overlap,
                "validation_test": len(set(dataset.template_ids) & set(validation_dataset.template_ids)),
            },
            "disjoint": validation_overlap == 0 and test_overlap == 0 and not (set(dataset.template_ids) & set(validation_dataset.template_ids)),
        }
        if not template_isolation["disjoint"]:
            parser.error("ONNX training, validation, and test template groups must be disjoint")
        try:
            import torch

            torch.set_num_threads(args.threads)
            export = export_transformer_onnx(args.model_dir, args.output_dir, quantize=not args.no_quantize)
        except (RuntimeError, ImportError) as exc:
            parser.error(str(exc))
        source_bundle = load_model(args.model_dir)
        float_bundle = load_onnx_bundle(args.output_dir, quantized=False, threads=args.threads)
        int8_bundle = load_onnx_bundle(args.output_dir, quantized=True, threads=args.threads) if export["quantized"] else None
        text_values, labels = dataset.texts, dataset.labels
        validation_texts, validation_labels = validation_dataset.texts, validation_dataset.labels
        source_threshold = choose_threshold(source_bundle["model"], validation_texts, validation_labels, ham_fpr_limit=args.ham_fpr_limit)
        float_threshold = choose_threshold(float_bundle["model"], validation_texts, validation_labels, ham_fpr_limit=args.ham_fpr_limit)
        int8_threshold = (
            choose_threshold(int8_bundle["model"], validation_texts, validation_labels, ham_fpr_limit=args.ham_fpr_limit)
            if int8_bundle is not None else None
        )
        onnx_metadata_path = Path(args.output_dir) / "metadata.json"
        onnx_metadata = json.loads(onnx_metadata_path.read_text(encoding="utf-8"))
        onnx_metadata["decision_threshold_float"] = float_threshold["threshold"]
        if int8_threshold is not None:
            onnx_metadata["decision_threshold_int8"] = int8_threshold["threshold"]
        else:
            onnx_metadata.pop("decision_threshold_int8", None)
        onnx_metadata["decision_threshold"] = int8_threshold["threshold"] if int8_threshold is not None else float_threshold["threshold"]
        onnx_metadata["threshold_calibration_ham_fpr_limit"] = args.ham_fpr_limit
        _write_json(onnx_metadata_path, onnx_metadata)
        float_bundle["decision_threshold"] = float_threshold["threshold"]
        if int8_bundle is not None:
            int8_bundle["decision_threshold"] = int8_threshold["threshold"]
        source_report = benchmark_predictor(source_bundle["model"], text_values, labels, threshold=source_threshold["threshold"], model_path=Path(args.model_dir) / "best_model", latency_limit=args.latency_samples)
        float_report = benchmark_predictor(float_bundle["model"], text_values, labels, threshold=float_threshold["threshold"], model_path=Path(args.output_dir) / "model.onnx", latency_limit=args.latency_samples)
        fp_metrics = float_report["metrics"]
        float_category_deltas = {
            category: fp_metrics["important_category_false_positive_rate"].get(category, 0.0) - source_report["metrics"]["important_category_false_positive_rate"].get(category, 0.0)
            for category in source_report["metrics"]["important_category_false_positive_rate"]
        }
        float_conversion_acceptance = {
            "max_important_fpr_increase": max(float_category_deltas.values(), default=0.0),
            "risk_recall_drop": (source_report["metrics"]["risk_recall"] or 0.0) - (fp_metrics["risk_recall"] or 0.0),
            "important_fpr_tolerance": 0.01,
            "risk_recall_tolerance": 0.02,
            "passed": max(float_category_deltas.values(), default=0.0) <= 0.01 and (source_report["metrics"]["risk_recall"] or 0.0) - (fp_metrics["risk_recall"] or 0.0) <= 0.02,
        }
        if int8_bundle is not None:
            int8_report = benchmark_predictor(int8_bundle["model"], text_values, labels, threshold=int8_threshold["threshold"], model_path=Path(args.output_dir) / "model.int8.onnx", latency_limit=args.latency_samples)
            q_metrics = int8_report["metrics"]
            category_deltas = {
                category: q_metrics["important_category_false_positive_rate"].get(category, 0.0) - fp_metrics["important_category_false_positive_rate"].get(category, 0.0)
                for category in fp_metrics["important_category_false_positive_rate"]
            }
            quantization_acceptance = {
                "max_important_fpr_increase": max(category_deltas.values(), default=0.0),
                "risk_recall_drop": (fp_metrics["risk_recall"] or 0.0) - (q_metrics["risk_recall"] or 0.0),
                "important_fpr_tolerance": 0.01,
                "risk_recall_tolerance": 0.02,
                "passed": max(category_deltas.values(), default=0.0) <= 0.01 and (fp_metrics["risk_recall"] or 0.0) - (q_metrics["risk_recall"] or 0.0) <= 0.02,
            }
        else:
            int8_report = None
            quantization_acceptance = {"status": "not_run", "passed": None, "reason": "INT8 quantization was disabled"}
        deployment_bundle = int8_bundle if int8_bundle is not None else float_bundle
        deployment_report = int8_report if int8_report is not None else float_report
        report = {
            "data": data_report.__dict__,
            "validation_data": validation_report.__dict__,
            "export": export,
            "threads": args.threads,
            "ham_fpr_limit": args.ham_fpr_limit,
            "validation_thresholds": {
                "pytorch": source_threshold,
                "onnx_float": float_threshold,
                "onnx_int8": int8_threshold,
            },
            "test_data_policy": _test_policy(dataset, list(range(len(dataset)))),
            "template_split_isolation": template_isolation,
            "model_classes": source_bundle["classes"],
            "model_version": deployment_bundle["version"],
            "deployment_runtime": "onnx_int8" if int8_bundle is not None else "onnx_float",
            "test": deployment_report["metrics"],
            "pytorch": source_report,
            "onnx_float": float_report,
            "onnx_int8": int8_report,
            "float_conversion_acceptance": float_conversion_acceptance,
            "quantization_acceptance": quantization_acceptance,
            "candidate_artifact_sha256": artifact_sha256(args.output_dir),
            "confidence_calibration": source_bundle.get("confidence_calibration", {}),
        }
        _write_json(args.report, report)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return

    _ensure_report_outside_artifact(args.report, args.model)
    model, splits = train_baseline(
        dataset,
        model_path=args.model,
        seed=args.seed,
        splits=training_splits,
        synthetic_loss_share=synthetic_loss_share,
    )
    isolation_report = template_split_report(dataset, splits)
    if not isolation_report["disjoint"]:
        parser.error("training split contains overlapping template groups")
    val = splits["validation"]
    threshold = choose_threshold(model, [dataset.texts[i] for i in val], [dataset.labels[i] for i in val], ham_fpr_limit=args.ham_fpr_limit)
    bundle = load_model(args.model)
    bundle["decision_threshold"] = threshold["threshold"]
    joblib.dump(bundle, args.model)
    test = splits["test"]
    report = {
        "data": data_report.__dict__,
        "split_sizes": {name: len(indices) for name, indices in splits.items()},
        "template_split_isolation": isolation_report,
        "test_data_policy": _test_policy(dataset, test),
        "model_classes": list(model.classes_),
        "validation_threshold_selection": threshold,
        "confidence_calibration": {
            "method": bundle.get("calibration_method"),
            "fitted_on": "group-isolated out-of-fold predictions from the training partition",
            "confidence_calibrated": bundle.get("confidence_calibrated", False),
        },
        "test": evaluate(model, [dataset.texts[i] for i in test], [dataset.labels[i] for i in test], threshold=threshold["threshold"], sample_ids=test),
        "model_version": "baseline-char-tfidf-lr-v1",
        "training_weight_policy": bundle.get("training_weight_policy"),
        "synthetic_loss_share_per_class": bundle.get("synthetic_loss_share_per_class"),
        "candidate_artifact_sha256": artifact_sha256(args.model),
    }
    _write_json(args.report, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
