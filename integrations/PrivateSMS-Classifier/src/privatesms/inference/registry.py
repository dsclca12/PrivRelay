from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path


_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
_BUSINESS_CLASSES = {"personal", "otp", "service", "transaction", "marketing", "suspicious", "uncertain"}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def artifact_sha256(path: str | Path) -> str:
    """Fingerprint exactly one candidate artifact, independent of its parent path."""
    target = Path(path)
    if target.is_symlink():
        raise ValueError("model artifacts cannot be symlinks")
    if target.is_file():
        return _sha256_file(target)
    if not target.is_dir():
        raise FileNotFoundError(target)

    def ignored_component(name: str) -> bool:
        return name == "training-checkpoint.pt" or name.endswith(".tmp") or (name.startswith(".") and name.endswith(".staging"))

    files = []
    for item in sorted(target.rglob("*")):
        if item.is_symlink():
            raise ValueError(f"model artifacts cannot contain symlinks: {item}")
        if not item.is_file() or any(ignored_component(part) for part in item.relative_to(target).parts):
            continue
        files.append((item.relative_to(target).as_posix(), item))
    if not files:
        raise ValueError("model artifact directory contains no files")
    digest = hashlib.sha256()
    digest.update(b"privatesms-directory-artifact-v1\0")
    for relative, item in files:
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(bytes.fromhex(_sha256_file(item)))
        digest.update(b"\n")
    return digest.hexdigest()


def _secure_tree(path: Path) -> None:
    for item in sorted(path.rglob("*"), key=lambda candidate: len(candidate.parts), reverse=True):
        if item.is_symlink():
            raise ValueError(f"model registry cannot contain symlinks: {item}")
        os.chmod(item, 0o700 if item.is_dir() else 0o600)
    os.chmod(path, 0o700)


class ModelRegistry:
    """Small local immutable version store with atomic active/previous pointers."""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.versions = self.root / "versions"
        self.pointer = self.root / "active.json"

    @staticmethod
    def _check_version(version: str) -> None:
        if not _VERSION.fullmatch(version) or version in {".", ".."}:
            raise ValueError("invalid model version name")

    def register(self, candidate: str | Path, version: str) -> dict:
        self._check_version(version)
        source = Path(candidate)
        if not source.exists():
            raise FileNotFoundError(source)
        source_artifact_sha256 = artifact_sha256(source)
        self.versions.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.root, 0o700)
        os.chmod(self.versions, 0o700)
        target = self.versions / version
        if target.exists():
            raise FileExistsError(f"version {version} is immutable and already registered")
        staging = self.versions / f".{version}.staging"
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir(mode=0o700)
        if source.is_dir():
            model_dir = staging / "model"
            shutil.copytree(source, model_dir, ignore=shutil.ignore_patterns("training-checkpoint.pt", "*.tmp", ".*.staging"), copy_function=shutil.copy2)
            _secure_tree(model_dir)
            model_rel = "model"
        else:
            model_file = staging / source.name
            shutil.copy2(source, model_file)
            os.chmod(model_file, 0o600)
            model_rel = source.name
        if artifact_sha256(staging / model_rel) != source_artifact_sha256:
            shutil.rmtree(staging)
            raise ValueError("candidate artifact changed while it was being registered")
        files = {}
        for path in sorted(p for p in staging.rglob("*") if p.is_file()):
            files[str(path.relative_to(staging))] = _sha256_file(path)
        manifest = {
            "version": version,
            "model_path": model_rel,
            "artifact_sha256": source_artifact_sha256,
            "registered_at": datetime.now(timezone.utc).isoformat(),
            "files_sha256": files,
        }
        manifest_path = staging / "manifest.json"
        fd = os.open(manifest_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        _secure_tree(staging)
        os.replace(staging, target)
        return manifest

    def _manifest(self, version: str) -> tuple[dict, Path]:
        self._check_version(version)
        root = self.versions / version
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        for relative, digest in manifest["files_sha256"].items():
            path = root / relative
            if not path.is_file() or _sha256_file(path) != digest:
                raise ValueError(f"model artifact integrity check failed: {relative}")
        actual_artifact_sha256 = artifact_sha256(root / manifest["model_path"])
        # Older registries predate the aggregate fingerprint. Their per-file
        # hashes are still checked above, so derive the fingerprint on read.
        if manifest.get("artifact_sha256") is None:
            manifest["artifact_sha256"] = actual_artifact_sha256
        if actual_artifact_sha256 != manifest["artifact_sha256"]:
            raise ValueError("model artifact fingerprint does not match its manifest")
        # Resolution is also used by the API, where the registry is mounted
        # read-only. Permission hardening belongs to register/activation, not
        # to this read path.
        return manifest, root

    def activate(self, version: str, *, evaluation_report: str | Path, max_risk_fpr: float = 0.01) -> Path:
        manifest, root = self._manifest(version)
        if not 0 <= max_risk_fpr <= 1:
            raise ValueError("max_risk_fpr must be between 0 and 1")
        report = json.loads(Path(evaluation_report).read_text(encoding="utf-8"))
        metrics = report.get("test", {})
        fpr = metrics.get("risk_false_positive_rate")
        if fpr is None:
            fpr = metrics.get("ham_false_positive_rate")
        if not isinstance(fpr, (int, float)) or not math.isfinite(fpr) or not 0 <= fpr <= 1 or fpr > max_risk_fpr:
            raise ValueError(f"candidate fails test-set risk FPR gate: {fpr!r} > {max_risk_fpr}")
        risk_recall = metrics.get("risk_recall", metrics.get("spam_recall"))
        if not isinstance(risk_recall, (int, float)) or not math.isfinite(risk_recall) or not 0 <= risk_recall <= 1:
            raise ValueError("evaluation report lacks a valid test-set risk recall")
        if metrics.get("samples", 0) < 1:
            raise ValueError("evaluation report has no independent test samples")
        classes = set(report.get("model_classes", []))
        if classes not in ({"ham", "spam"}, _BUSINESS_CLASSES):
            raise ValueError("evaluation report model classes must be ham/spam or the complete seven-class schema")
        if classes == _BUSINESS_CLASSES:
            calibration = report.get("confidence_calibration", {})
            if calibration.get("confidence_calibrated") is not True or calibration.get("method") != "temperature_scaling":
                raise ValueError("seven-class candidate lacks validation temperature calibration evidence")
            ece = metrics.get("probability_calibration", {}).get("top_label_ece")
            if not isinstance(ece, (int, float)) or not math.isfinite(ece) or not 0 <= ece <= 0.10:
                raise ValueError("seven-class candidate test top-label ECE must be between 0 and 0.10")
        per_class = metrics.get("per_class", {})
        supports = {
            label: values.get("support")
            for label, values in per_class.items()
            if isinstance(values, dict)
        }
        if any(not isinstance(supports.get(label), (int, float)) or supports[label] <= 0 for label in classes):
            raise ValueError("test report does not prove positive support for every model class")
        if sum(supports[label] for label in classes) != metrics["samples"]:
            raise ValueError("test per-class support does not match the total test sample count")
        test_policy = report.get("test_data_policy", {})
        if test_policy.get("training_only_rows") != 0 or test_policy.get("synthetic_rows") != 0 or test_policy.get("samples") != metrics.get("samples"):
            raise ValueError("evaluation report does not prove a non-synthetic, training-only-free test set")
        isolation = report.get("template_split_isolation", {})
        overlaps = isolation.get("overlap_groups", {})
        if not isolation.get("disjoint") or any(overlaps.get(name) != 0 for name in ("train_validation", "train_test", "validation_test")):
            raise ValueError("evaluation report does not prove template-group isolation across train/validation/test")
        important = metrics.get("important_category_false_positive_rate", {})
        required_important = {"ham"} if classes and classes <= {"ham", "spam"} else {"personal", "otp", "service", "transaction"} if classes else set()
        missing_important = required_important - set(important)
        if missing_important:
            raise ValueError(f"test report lacks required important-category measurements: {sorted(missing_important)}")
        invalid_important = {
            label: value for label, value in important.items()
            if not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1
        }
        if invalid_important:
            raise ValueError(f"test report has invalid important-category FPR values: {invalid_important}")
        breaches = {label: value for label, value in important.items() if value > max_risk_fpr}
        if breaches:
            raise ValueError(f"candidate fails important-category FPR gate: {breaches}")
        if report.get("candidate_artifact_sha256") != manifest.get("artifact_sha256"):
            raise ValueError("evaluation report artifact fingerprint does not match the registered candidate")
        current = self._read_pointer()
        if current.get("active_version") == version:
            raise ValueError(f"version {version} is already active")
        pointer = {"active_version": version, "previous_version": current.get("active_version"), "activated_at": datetime.now(timezone.utc).isoformat()}
        self._write_pointer(pointer)
        return root / manifest["model_path"]

    def rollback(self) -> Path:
        current = self._read_pointer()
        previous = current.get("previous_version")
        if not previous:
            raise ValueError("no previous model version is available")
        manifest, root = self._manifest(previous)
        pointer = {"active_version": previous, "previous_version": current.get("active_version"), "activated_at": datetime.now(timezone.utc).isoformat()}
        self._write_pointer(pointer)
        return root / manifest["model_path"]

    def current(self) -> dict:
        pointer = self._read_pointer()
        if pointer.get("active_version"):
            manifest, root = self._manifest(pointer["active_version"])
            pointer["model_path"] = str(root / manifest["model_path"])
        return pointer

    def resolve(self) -> Path:
        pointer = self.current()
        if not pointer.get("model_path"):
            raise FileNotFoundError("no active model version registered")
        return Path(pointer["model_path"])

    def _read_pointer(self) -> dict:
        if not self.pointer.exists():
            return {}
        return json.loads(self.pointer.read_text(encoding="utf-8"))

    def _write_pointer(self, pointer: dict) -> None:
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.root, 0o700)
        temporary = self.pointer.with_suffix(".json.tmp")
        fd = os.open(temporary, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(pointer, ensure_ascii=False, indent=2) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, self.pointer)


def resolve_model_path(*, model_path: str | Path | None = None, registry_path: str | Path | None = None, fallback: str | Path = "artifacts/baseline.joblib") -> Path:
    explicit = model_path or os.getenv("PRIVATESMS_MODEL_PATH")
    if explicit:
        return Path(explicit)
    registry = ModelRegistry(registry_path or os.getenv("PRIVATESMS_MODEL_REGISTRY", "artifacts/model_registry"))
    if not registry.pointer.exists():
        return Path(fallback)
    return registry.resolve()
