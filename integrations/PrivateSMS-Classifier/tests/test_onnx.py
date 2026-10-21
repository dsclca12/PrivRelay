import json

import pytest


def test_onnx_bundle_loads_runtime_specific_calibrated_thresholds(tmp_path, monkeypatch):
    ort = pytest.importorskip("onnxruntime")
    transformers = pytest.importorskip("transformers")
    from privatesms.inference.onnx import load_onnx_bundle

    (tmp_path / "model.onnx").write_bytes(b"float")
    (tmp_path / "model.int8.onnx").write_bytes(b"int8")
    (tmp_path / "metadata.json").write_text(json.dumps({
        "classes": ["ham", "spam"],
        "max_length": 128,
        "decision_threshold": 0.9639,
        "decision_threshold_float": 0.9639,
        "decision_threshold_int8": 0.8446,
    }), encoding="utf-8")

    class Session:
        def __init__(self, *args, **kwargs):
            pass

        def get_providers(self):
            return ["CPUExecutionProvider"]

    class Tokenizer:
        pass

    monkeypatch.setattr(ort, "InferenceSession", Session)
    monkeypatch.setattr(transformers.AutoTokenizer, "from_pretrained", lambda *args, **kwargs: Tokenizer())

    float_bundle = load_onnx_bundle(tmp_path, quantized=False, threads=2)
    int8_bundle = load_onnx_bundle(tmp_path, quantized=True, threads=2)

    assert float_bundle["decision_threshold"] == pytest.approx(0.9639)
    assert int8_bundle["decision_threshold"] == pytest.approx(0.8446)

    metadata_path = tmp_path / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["quantization"] = "disabled-copy"
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    with pytest.raises(ValueError, match="quantization disabled"):
        load_onnx_bundle(tmp_path, quantized=True, threads=2)


def test_rbt_style_export_preserves_token_type_ids_and_dynamic_shapes(tmp_path):
    torch = pytest.importorskip("torch")
    ort = pytest.importorskip("onnxruntime")
    transformers = pytest.importorskip("transformers")
    from privatesms.inference.onnx import load_onnx_bundle
    from privatesms.inference.onnx_export import export_transformer_onnx
    from privatesms.inference.transformer import load_transformer_bundle

    model_dir = tmp_path / "source"
    best_dir = model_dir / "best_model"
    best_dir.mkdir(parents=True)
    vocab = ["[PAD]", "[UNK]", "[CLS]", "[SEP]", "[MASK]", "hello", "world", "中", "文", "短", "信"]
    (best_dir / "vocab.txt").write_text("\n".join(vocab) + "\n", encoding="utf-8")
    tokenizer = transformers.BertTokenizer(str(best_dir / "vocab.txt"))
    tokenizer.save_pretrained(best_dir)
    config = transformers.BertConfig(
        vocab_size=len(vocab), hidden_size=16, num_hidden_layers=1,
        num_attention_heads=2, intermediate_size=32, max_position_embeddings=32,
        type_vocab_size=2, num_labels=2,
    )
    transformers.BertForSequenceClassification(config).save_pretrained(best_dir)
    (model_dir / "metadata.json").write_text(json.dumps({
        "classes": ["ham", "spam"], "max_length": 24, "version": "test-rbt",
        "decision_threshold": 0.5,
    }), encoding="utf-8")

    export_transformer_onnx(model_dir, tmp_path / "onnx", quantize=True)
    source = load_transformer_bundle(model_dir)["model"]
    float_bundle = load_onnx_bundle(tmp_path / "onnx", quantized=False, threads=2)
    int8_bundle = load_onnx_bundle(tmp_path / "onnx", quantized=True, threads=2)
    assert "token_type_ids" in {item.name for item in float_bundle["model"].session.get_inputs()}

    for batch_texts in (["hello"], ["hello world", "中文短信"]):
        encoded = source.tokenizer(batch_texts, truncation=True, max_length=24, padding=True, return_tensors="pt")
        with torch.inference_mode():
            expected = source.model(**encoded).logits.cpu().numpy()
        actual = float_bundle["model"].session.run(
            ["logits"], {key: value.cpu().numpy() for key, value in encoded.items()}
        )[0]
        assert actual.shape == expected.shape
        assert abs(actual - expected).max() < 1e-5
        assert len(int8_bundle["model"].predict_proba(batch_texts)) == len(batch_texts)
