import json

import joblib
import numpy as np
import pytest

from privatesms.evaluation import evaluate
from privatesms.inference import load_model, predict
from privatesms.inference.ensemble import CommitteePredictor
from privatesms.training.multiclass import CATEGORIES


class ToyMember:
    def __init__(self, classes, rows):
        self.classes_ = classes
        self.rows = rows
        self.calls = []

    def predict_proba(self, texts):
        self.calls.append(list(texts))
        return [self.rows[text] for text in texts]


def test_aligns_different_class_orders_and_missing_uncertain_head():
    left = ToyMember(["otp", "personal"], {"text": [.9, .1]})
    right = ToyMember(["personal", "otp"], {"text": [.1, .9]})
    model = CommitteePredictor([left, right], classes=CATEGORIES, mode="consensus")
    detail = model.predict_with_details(["text"])
    assert detail["probabilities"][0, CATEGORIES.index("otp")] == pytest.approx(.9)
    assert detail["probabilities"].sum() == pytest.approx(1)
    assert not detail["review_mask"][0]
    assert not detail["abstain_mask"][0]


def test_disagreement_abstains_without_fabricating_uncertain_probability():
    left = ToyMember(["personal", "suspicious"], {"text": [.9, .1]})
    right = ToyMember(["suspicious", "personal"], {"text": [.8, .2]})
    model = CommitteePredictor([left, right], classes=CATEGORIES, mode="consensus")
    bundle = {"model": model, "classes": CATEGORIES, "version": "test", "category_decision": "argmax"}
    result = predict(bundle, "text")
    assert result["category"] == "uncertain"
    assert result["needs_review"] and not result["is_spam"]
    assert result["confidence"] == pytest.approx(.55)
    score = evaluate(model, ["text"], ["personal"], category_decision="argmax")
    assert score["accuracy"] == 0
    assert score["selective_policy"]["coverage"] == 0
    assert score["selective_policy"]["accepted_accuracy"] is None


def test_cascade_only_calls_reviewer_for_routed_rows_and_always_checks_risk():
    labels = ["otp", "suspicious"]
    fast = ToyMember(labels, {"easy": [.99, .01], "hard": [.55, .45], "risk": [.01, .99]})
    reviewer = ToyMember(labels, {"hard": [.4, .6], "risk": [.01, .99]})
    model = CommitteePredictor([fast, reviewer], classes=CATEGORIES, mode="cascade", weights=[.25, .75])
    details = model.predict_with_details(["easy", "hard", "risk"])
    assert reviewer.calls == [["hard", "risk"]]
    assert details["routed_mask"].tolist() == [False, True, True]
    assert details["abstain_mask"].tolist() == [False, True, False]
    assert details["probabilities"].sum(axis=1) == pytest.approx(np.ones(3))
    for i, text in enumerate(["easy", "hard", "risk"]):
        single = model.predict_with_details([text])
        assert single["probabilities"][0] == pytest.approx(details["probabilities"][i])
        assert single["abstain_mask"][0] == details["abstain_mask"][i]


def test_cascade_routes_rows_that_fail_the_final_confidence_gate():
    fast = ToyMember(["otp", "personal"], {"text": [.85, .15]})
    reviewer = ToyMember(["otp", "personal"], {"text": [.99, .01]})
    model = CommitteePredictor([fast, reviewer], classes=CATEGORIES, mode="cascade", fast_threshold=.8, review_threshold=.95)
    assert model.predict_with_details(["text"])["routed_mask"][0]
    assert reviewer.calls == [["text"]]


def test_shared_errors_are_not_misreported_as_proven_reliability():
    member = ToyMember(["otp", "suspicious"], {"text": [.01, .99]})
    model = CommitteePredictor([member, member], classes=CATEGORIES, mode="consensus")
    result = evaluate(model, ["text"], ["otp"], category_decision="argmax")
    assert result["selective_policy"]["disagreement_rate"] == 0
    assert result["selective_policy"]["coverage"] == 1
    assert result["selective_policy"]["accepted_accuracy"] == 0
    assert result["selective_policy"]["accepted_risk_false_positive_rate"] == 1


@pytest.mark.parametrize("weights", [[0, 0], [float("nan"), 1], [-1, 1], [1]])
def test_rejects_invalid_weights(weights):
    member = ToyMember(["otp", "personal"], {"text": [.9, .1]})
    with pytest.raises(ValueError, match="Weights"):
        CommitteePredictor([member, member], classes=CATEGORIES, weights=weights)


def test_rejects_invalid_member_probabilities():
    member = ToyMember(["otp", "personal"], {"text": [.9, .2]})
    model = CommitteePredictor([member], classes=CATEGORIES)
    with pytest.raises(ValueError, match="probabilities"):
        model.predict_proba(["text"])


def test_ensemble_artifact_round_trip_and_path_confinement(tmp_path):
    member = ToyMember(["otp", "personal"], {"text": [.9, .1]})
    joblib.dump({"model": member, "classes": member.classes_, "version": "member"}, tmp_path / "member.joblib")
    metadata = {"model_type": "ensemble", "classes": CATEGORIES, "version": "ensemble-test",
                "category_decision": "argmax", "confidence_calibrated": True,
                "members": [{"path": "member.joblib"}], "committee": {"mode": "consensus"}}
    (tmp_path / "metadata.json").write_text(json.dumps(metadata))
    restored = load_model(tmp_path)
    assert predict(restored, "text")["category"] == "otp"
    assert not restored["confidence_calibrated"]
    metadata["members"][0]["path"] = "../outside.joblib"
    (tmp_path / "metadata.json").write_text(json.dumps(metadata))
    with pytest.raises(ValueError, match="inside"):
        load_model(tmp_path)


def test_single_model_policy_is_a_fair_confidence_only_baseline():
    member = ToyMember(["otp", "personal"], {"text": [.9, .1]})
    model = CommitteePredictor([member], classes=CATEGORIES)
    result = evaluate(model, ["text"], ["otp"], category_decision="argmax")
    assert result["selective_policy"]["reviewer_call_rate"] == 0
    assert result["selective_policy"]["coverage"] == 1


def test_temperature_normalization_preserves_member_vote_and_missing_class_zeros():
    member = ToyMember(["otp", "personal"], {"text": [.9, .1]})
    model = CommitteePredictor([member], classes=CATEGORIES, temperatures=[2.0])
    probabilities = model.predict_proba(["text"])[0]
    assert probabilities[CATEGORIES.index("otp")] == pytest.approx(.75)
    assert probabilities[CATEGORIES.index("uncertain")] == 0
    assert CATEGORIES[int(probabilities.argmax())] == "otp"
    assert probabilities.sum() == pytest.approx(1)
    with pytest.raises(ValueError, match="temperatures"):
        CommitteePredictor([member], classes=CATEGORIES, temperatures=[float("nan")])
