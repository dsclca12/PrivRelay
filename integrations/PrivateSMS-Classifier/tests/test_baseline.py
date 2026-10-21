from pathlib import Path

from privatesms.datasets import prepare_dataset
from privatesms.inference import load_model, predict
from privatesms.training import train_baseline


def test_train_save_reload_predict(tmp_path: Path):
    rows = []
    for i in range(20):
        suffix = chr(0x4e00 + i)
        rows.append((f"你好朋友今天一起吃饭，约在公园场景{suffix}", "ham"))
        rows.append((f"贷款推广低息申请链接促销，活动场景{suffix}", "spam"))
    data, _ = prepare_dataset(rows)
    model_path = tmp_path / "baseline.joblib"
    train_baseline(data, model_path=model_path)
    assert model_path.stat().st_mode & 0o777 == 0o600
    loaded = load_model(model_path)
    result = predict(loaded, "低息贷款推广申请")
    assert result["category"] in {"ham", "spam"}
    assert 0 <= result["spam_score"] <= 1
    assert 0 <= result["confidence"] <= 1
    assert result["confidence_calibrated"] is True
    assert loaded["calibration_method"] == "grouped-oof-logistic"
    assert loaded["version"] == "baseline-char-tfidf-lr-v1"
    assert "decision_threshold" in loaded
    assert predict(loaded, "低息贷款推广申请", threshold=1.0)["category"] == "ham"
