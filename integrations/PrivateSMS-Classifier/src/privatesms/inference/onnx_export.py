from __future__ import annotations

import json
import inspect
import os
import shutil
from pathlib import Path


def export_transformer_onnx(model_dir: str | Path, output_dir: str | Path, *, quantize: bool = True) -> dict:
    try:
        import onnx
        import onnxruntime as ort
        import torch
        from onnxruntime.quantization import QuantType, quantize_dynamic
        from transformers import AutoTokenizer
    except ImportError as exc:
        raise RuntimeError("Install PyTorch CPU, Transformers, ONNX, and ONNX Runtime optional dependencies") from exc
    from .transformer import load_transformer_bundle

    source = Path(model_dir)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    bundle = load_transformer_bundle(source)
    predictor = bundle["model"]
    model = predictor.model.cpu().eval()
    tokenizer = predictor.tokenizer
    max_length = int(bundle["max_length"])

    accepts_token_type_ids = "token_type_ids" in inspect.signature(model.forward).parameters

    class LogitsOnly(torch.nn.Module):
        def __init__(self, wrapped, *, include_token_type_ids: bool):
            super().__init__()
            self.wrapped = wrapped
            self.include_token_type_ids = include_token_type_ids

        def forward(self, input_ids, attention_mask, token_type_ids=None):
            inputs = {"input_ids": input_ids, "attention_mask": attention_mask}
            if self.include_token_type_ids and token_type_ids is not None:
                inputs["token_type_ids"] = token_type_ids
            return self.wrapped(**inputs).logits

    wrapper = LogitsOnly(model, include_token_type_ids=accepts_token_type_ids).eval()
    sample = tokenizer(["短信推理导出样例"], truncation=True, max_length=max_length, padding="max_length", return_tensors="pt")
    export_inputs = [sample["input_ids"], sample["attention_mask"]]
    input_names = ["input_ids", "attention_mask"]
    dynamic_axes = {
        "input_ids": {0: "batch", 1: "sequence"},
        "attention_mask": {0: "batch", 1: "sequence"},
        "logits": {0: "batch"},
    }
    if accepts_token_type_ids and "token_type_ids" in sample:
        export_inputs.append(sample["token_type_ids"])
        input_names.append("token_type_ids")
        dynamic_axes["token_type_ids"] = {0: "batch", 1: "sequence"}
    float_model = output / "model.onnx"
    torch.onnx.export(
        wrapper,
        tuple(export_inputs),
        str(float_model),
        input_names=input_names,
        output_names=["logits"],
        dynamic_axes=dynamic_axes,
        opset_version=17,
        dynamo=False,
    )
    onnx.checker.check_model(str(float_model))
    float_session_options = ort.SessionOptions()
    float_session_options.intra_op_num_threads = 1
    float_session_options.inter_op_num_threads = 1
    float_session = ort.InferenceSession(str(float_model), sess_options=float_session_options, providers=["CPUExecutionProvider"])
    if "CPUExecutionProvider" not in float_session.get_providers():
        raise RuntimeError("ONNX Runtime did not load CPUExecutionProvider for the float model")
    with torch.inference_mode():
        expected_logits = wrapper(*export_inputs).detach().cpu().numpy()
    actual_logits = float_session.run(
        ["logits"],
        {name: value.detach().cpu().numpy() for name, value in zip(input_names, export_inputs)},
    )[0]
    import numpy as np

    max_abs_logit_error = float(np.max(np.abs(expected_logits - actual_logits)))
    if not np.allclose(expected_logits, actual_logits, rtol=1e-4, atol=1e-4):
        raise RuntimeError(f"ONNX float export does not match PyTorch (max abs logit error {max_abs_logit_error:.6g})")
    int8_model = output / "model.int8.onnx"
    if quantize:
        quantize_dynamic(str(float_model), str(int8_model), weight_type=QuantType.QInt8, op_types_to_quantize=["MatMul", "Gemm"])
        onnx.checker.check_model(str(int8_model))
    else:
        shutil.copy2(float_model, int8_model)

    tokenizer.save_pretrained(output)
    training_manifest = source / "training-template-ids.json"
    if training_manifest.is_file():
        copied_manifest = output / training_manifest.name
        shutil.copy2(training_manifest, copied_manifest)
        os.chmod(copied_manifest, 0o600)
    metadata = {key: value for key, value in bundle.items() if key != "model"}
    metadata["onnx_opset"] = 17
    metadata["quantization"] = "dynamic-int8-qint8" if quantize else "disabled-copy"
    metadata["decision_threshold"] = bundle.get("decision_threshold", 0.5)
    metadata["onnx_inputs"] = input_names
    metadata["float_export_validation"] = {
        "provider": float_session.get_providers(),
        "batch_size": 1,
        "sequence_length": max_length,
        "max_abs_logit_error": max_abs_logit_error,
        "passed": True,
    }
    (output / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    options = ort.SessionOptions()
    options.intra_op_num_threads = 1
    options.inter_op_num_threads = 1
    session = ort.InferenceSession(str(int8_model), sess_options=options, providers=["CPUExecutionProvider"])
    if "CPUExecutionProvider" not in session.get_providers():
        raise RuntimeError("ONNX Runtime did not load CPUExecutionProvider")
    return {
        "output_dir": str(output),
        "float_model": str(float_model),
        "int8_model": str(int8_model),
        "providers": session.get_providers(),
        "quantized": quantize,
        "float_export_validation": metadata["float_export_validation"],
    }
