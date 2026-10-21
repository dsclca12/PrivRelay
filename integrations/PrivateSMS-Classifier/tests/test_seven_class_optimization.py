import importlib.util
import json
from dataclasses import asdict
from pathlib import Path

import joblib
import numpy as np
import pytest

from privatesms.datasets import prepare_dataset
from privatesms.evaluation import evaluate
from privatesms.inference import load_model, predict
from privatesms.training.multiclass import CATEGORIES, SparseConfig, fit_sparse_model, source_balanced_weights


def test_source_balance_uses_effective_counts_and_preserves_human_trust():
    labels = ["service", "service", "service", "otp"]
    weights = source_balanced_weights(labels, ["human", "ai", "ai", "ai"], ai_weight=0.1)
    assert weights[0] / weights[1] == pytest.approx(10)
    assert sum(weights[:3]) == pytest.approx(weights[3])
    assert sum(weights) == pytest.approx(len(labels))
    rare_weights = source_balanced_weights(["service", "uncertain"], ["human", "ai"], ai_weight=0.1, uncertain_weight=0.25)
    assert rare_weights[1] / rare_weights[0] == pytest.approx(0.25)
    with pytest.raises(ValueError):
        source_balanced_weights(labels, ["ai"] * 4, ai_weight=float("nan"))


@pytest.mark.parametrize("classifier", ["logistic", "svm", "complement_nb", "multinomial_nb"])
def test_seven_class_artifact_reload_preserves_probabilities(tmp_path, classifier):
    texts = ["周末一起吃饭吧", "您的验证码123456请勿泄露", "快递已到驿站请凭取件码领取",
             "银行卡消费支出人民币十元", "会员专享限时优惠满减立即选购", "安装远控软件共享屏幕并转账到安全账户", "点这里"]
    labels = ["personal", "otp", "service", "transaction", "marketing", "suspicious", "uncertain"]
    model = fit_sparse_model(texts, labels, ["ai"] * 7, SparseConfig(classifier=classifier))
    path = tmp_path / "model.joblib"
    joblib.dump({"model": model, "classes": model.classes_, "version": "seven-test", "category_decision": "argmax"}, path)
    restored = load_model(path)
    probabilities = restored["model"].predict_proba(texts)
    assert list(model.classes_) == CATEGORIES
    assert np.isfinite(probabilities).all()
    assert probabilities.sum(axis=1) == pytest.approx(np.ones(7))
    assert probabilities == pytest.approx(model.predict_proba(texts))
    assert model.predict_proba([texts[0]]) == pytest.approx(model.predict_proba([f"　{texts[0]}　"]))
    assert predict(restored, "点这里")["category"] == "uncertain"


def test_argmax_category_is_not_replaced_by_risk_threshold():
    class Borderline:
        classes_ = CATEGORIES

        def predict_proba(self, texts):
            return [[0.28, 0.03, 0.02, 0.35, 0.12, 0.05, 0.15] for _ in texts]

    bundle = {"model": Borderline(), "classes": CATEGORIES, "version": "test", "category_decision": "argmax"}
    result = predict(bundle, "message", threshold=0.3)
    assert result["category"] == "service"
    assert result["is_spam"] is True
    assert result["needs_review"] is True
    report = evaluate(Borderline(), ["message"], ["service"], threshold=0.3, category_decision="argmax")
    assert report["accuracy"] == 1.0
    assert report["risk_false_positive_rate"] == 1.0


def test_argmax_uncertain_is_not_spam_even_when_risk_mass_exceeds_threshold():
    class Ambiguous:
        classes_ = CATEGORIES

        def predict_proba(self, texts):
            return [[0.28, 0.01, 0.01, 0.01, 0.27, 0.01, 0.41] for _ in texts]

    bundle = {"model": Ambiguous(), "classes": CATEGORIES, "version": "test", "category_decision": "argmax"}
    result = predict(bundle, "message")
    assert result["category"] == "uncertain"
    assert result["is_spam"] is False
    assert result["needs_review"] is True
    assert evaluate(Ambiguous(), ["message"], ["uncertain"], category_decision="argmax")["accuracy"] == 1.0


def optimization_script():
    spec = importlib.util.spec_from_file_location("optimize_seven_class", Path(__file__).parents[1] / "scripts/optimize_seven_class.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_validation_cache_does_not_change_accuracy_selection_priority():
    module = optimization_script()
    candidates = [SparseConfig(c=1), SparseConfig(c=4)]
    rows = [
        {"config": asdict(candidates[0]), "accuracy": 0.9, "macro_f1": 0.7},
        {"config": asdict(candidates[1]), "accuracy": 0.8, "macro_f1": 0.95},
    ]
    cached = module.merge_validation_scores([rows])
    selected, scores = module.select_config(None, None, [], candidates, seed=42, folds=3, cached_scores=cached)
    assert selected == candidates[0]
    assert scores == rows
    with pytest.raises(ValueError, match="Conflicting"):
        module.merge_validation_scores([rows, [{**rows[0], "accuracy": 0.1}]])


def test_private_report_refuses_to_replace_existing_evidence(tmp_path):
    module = optimization_script()
    path = tmp_path / "evaluation.json"
    module.private_json(path, {"accuracy": 0.9})
    assert path.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        module.private_json(path, {"accuracy": 1.0})
    assert json.loads(path.read_text()) == {"accuracy": 0.9}
    assert list(tmp_path.iterdir()) == [path]


def test_rare_class_grouped_folds_cover_each_row_once():
    module = optimization_script()
    data, _ = prepare_dataset([("天气很好一起散步", "personal"), ("晚上到家再联系", "personal"),
                               ("明天安排尚未决定", "personal"), ("点这里", "uncertain")])
    folds = list(module.grouped_folds(data, list(range(len(data))), 3, 42))
    heldout = [i for _, test in folds for i in test]
    assert sorted(heldout) == list(range(len(data)))
    assert len(heldout) == len(set(heldout))
    for train, test in folds:
        assert not set(data.template_ids[i] for i in train) & set(data.template_ids[i] for i in test)


def test_evaluation_rejects_unverified_labels(tmp_path):
    module = optimization_script()
    human = tmp_path / "human.jsonl"
    human.write_text(json.dumps({"text": "样本", "category": "otp", "source": "teacher_synthetic", "human_verified": False}))
    with pytest.raises(ValueError, match="human-verified"):
        module.prepare_corpora(human, [])


def test_cross_source_overlap_is_removed_regardless_of_ai_label(tmp_path):
    module = optimization_script()
    human = tmp_path / "human.jsonl"
    human.write_text(json.dumps({"text": "您的验证码123456请勿泄露", "label": "otp", "category": "otp",
                                "source": "human", "human_verified": True}, ensure_ascii=False) + "\n")
    ai = tmp_path / "ai.jsonl"
    texts = ["夏季会员优惠折扣", "登录动态码654321", "今晚一起去看电影", "您的航班提前登机",
             "安装远控软件转账到安全账户", "银行卡已扣款五百元", "打开此处"]
    rows = [{"text": text, "category": label, "label": label} for text, label in zip(texts, CATEGORIES)]
    rows.append({"text": "您的验证码654321请勿泄露", "category": "marketing", "label": "marketing"})
    ai.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows))
    _, retained, report = module.prepare_corpora(human, [ai])
    assert "您的验证码654321请勿泄露" not in retained.texts
    assert report["ai_removed_for_human_overlap"] == 1
