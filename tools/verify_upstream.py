"""Verify the ordinary source snapshot, including its exact model bytes."""
import hashlib
import json
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    source = root / "integrations/PrivateSMS-Classifier"
    expected = json.loads((root / "integrations/UPSTREAM_FILES.json").read_text())
    if (source / ".git").exists() or (root / ".gitmodules").exists():
        raise SystemExit("Nested Git metadata is not allowed for this integration")
    for name, digest in expected.items():
        data = (source / name).read_bytes()
        if not name.endswith((".onnx", ".safetensors", ".joblib")):
            data = data.replace(b"\r\n", b"\n")
        if hashlib.sha256(data).hexdigest() != digest:
            raise SystemExit(f"Upstream content changed: {name}")
    print(f"PASS {len(expected)} upstream files and model checksums; no nested Git metadata")


if __name__ == "__main__":
    main()
