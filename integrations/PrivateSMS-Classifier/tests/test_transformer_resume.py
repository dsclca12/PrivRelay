from dataclasses import replace

from privatesms.datasets import prepare_dataset
from privatesms.training.transformer import _training_fingerprint


def test_transformer_fingerprint_binds_rows_splits_and_training_settings():
    dataset, _ = prepare_dataset([
        ("收到验证码 123456", "ham"),
        ("会议时间下午三点", "ham"),
        ("点击链接领取贷款", "spam"),
        ("立即申请低息贷款", "spam"),
    ])
    splits = {"train": [0, 2], "validation": [1], "test": [3]}
    options = dict(model_name="local/rbt3", classes=["ham", "spam"], seed=42, batch_size=2, max_length=64, learning_rate=2e-5)
    expected = _training_fingerprint(dataset, splits, **options)

    assert _training_fingerprint(dataset, splits, **options) == expected
    assert _training_fingerprint(replace(dataset, texts=[*dataset.texts[:-1], "changed message"]), splits, **options) != expected
    assert _training_fingerprint(dataset, {**splits, "train": [0, 3]}, **options) != expected
    assert _training_fingerprint(dataset, splits, **{**options, "learning_rate": 1e-5}) != expected
