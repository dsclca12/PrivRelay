import json

import pytest

from privatesms.datasets import load_dataset
from privatesms.cli import main
from privatesms.labeling import assisted
from privatesms.labeling.assisted import GenerationError, label_public_dataset
from privatesms.labeling import review_teacher_suggestions
from privatesms.generators import synthetic


def _set_teacher_env(monkeypatch):
    monkeypatch.setenv("PRIVATESMS_TEACHER_BASE_URL", "https://teacher.example.invalid/v1")
    monkeypatch.setenv("PRIVATESMS_TEACHER_MODEL", "configured-model-id")
    monkeypatch.setenv("PRIVATESMS_TEACHER_API_KEY", "test-secret")
    monkeypatch.setenv("PRIVATESMS_INPUT_PRICE_PER_1M", "1")
    monkeypatch.setenv("PRIVATESMS_OUTPUT_PRICE_PER_1M", "2")


def test_redaction_catches_common_spaced_and_hyphenated_identifiers():
    text = "电话138-1234-5678，卡号6222 0212 3456 7890，证件110105 19491231 002X，邮箱a@example.com"
    redacted = assisted._redact_for_teacher(text)
    for raw in ("138-1234-5678", "6222 0212 3456 7890", "110105 19491231 002X", "a@example.com"):
        assert raw not in redacted
    assert "<PHONE>" in redacted and "<ACCOUNT>" in redacted and "<ID>" in redacted and "<EMAIL>" in redacted


def test_public_label_suggestions_redact_egress_and_remain_train_only(monkeypatch, tmp_path):
    _set_teacher_env(monkeypatch)
    source = tmp_path / "public.tsv"
    source.write_text(
        "0\t验证码 13812345678，请访问 https://login.example.com/a\n"
        "1\t申请低息贷款点击链接领取优惠\n",
        encoding="utf-8",
    )
    output = tmp_path / "assisted.jsonl"
    calls = []

    def fake_request(prompt, config, *, system_message, max_completion_tokens, temperature, **kwargs):
        calls.append((prompt, system_message, max_completion_tokens, temperature))
        return {"category": "otp", "confidence": 0.91}, {"prompt_tokens": 100, "completion_tokens": 20}

    monkeypatch.setattr(assisted, "_request", fake_request)
    result = label_public_dataset(
        input_path=source,
        output_path=output,
        count=2,
        max_cost_usd=1,
        allow_remote=True,
        env_allow=True,
        confirm_public_egress=True,
        sleeper=lambda _: None,
    )
    assert result["annotated_this_run"] == 2
    assert result["human_review_required"] is True
    assert len(calls) == 2
    assert all("13812345678" not in prompt and "https://login.example.com" not in prompt for prompt, *_ in calls)
    assert "<PHONE>" in calls[0][0] and "<URL>" in calls[0][0]
    assert "不可信数据" in calls[0][1]
    assert calls[0][2:] == (64, 0.0)

    records = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert all(row["source"] == "teacher_assisted" and row["training_only"] for row in records)
    assert all(row["human_verified"] is False and row["synthetic"] is False for row in records)
    assert all(row["label_status"] == "teacher_suggestion_pending_human_review" for row in records)
    excluded, report = load_dataset(output)
    assert len(excluded) == 0 and report.excluded_training_only_rows == 2
    included, included_report = load_dataset(output, include_feedback=True)
    assert len(included) == 0 and included_report.excluded_training_only_rows == 2

    reviewed_path = tmp_path / "reviewed.jsonl"
    decisions = iter(["otp", None])
    review_report = review_teacher_suggestions(
        input_path=output,
        output_path=reviewed_path,
        decision_provider=lambda row, index: next(decisions),
        max_records=2,
    )
    assert review_report["suggestions_reviewed"] == 2
    assert review_report["human_verified_rows"] == 1
    reviewed, reviewed_data_report = load_dataset(reviewed_path, include_feedback=True)
    assert len(reviewed) == 1 and reviewed.labels == ["otp"]
    assert reviewed.training_only == [True]
    assert reviewed_data_report.included_training_only_rows == 1
    assert load_dataset(reviewed_path)[0].texts == []

    resumed = label_public_dataset(
        input_path=source,
        output_path=output,
        count=2,
        max_cost_usd=1,
        allow_remote=True,
        env_allow=True,
        confirm_public_egress=True,
        sleeper=lambda _: None,
    )
    assert resumed["annotated_this_run"] == 0
    assert len(calls) == 2


def test_public_labeling_requires_egress_confirmation_and_both_switches(tmp_path):
    source = tmp_path / "public.tsv"
    source.write_text("0\t一条公开短信样本\n", encoding="utf-8")
    options = dict(input_path=source, output_path=tmp_path / "labels.jsonl", count=1, max_cost_usd=1)
    with pytest.raises(GenerationError, match="(?i)public-data egress"):
        label_public_dataset(**options, allow_remote=True, env_allow=True, confirm_public_egress=False)
    with pytest.raises(GenerationError, match="PRIVATESMS_ALLOW_PUBLIC_LABELING_API"):
        label_public_dataset(**options, allow_remote=True, env_allow=False, confirm_public_egress=True)


def test_invalid_provider_prices_are_rejected(monkeypatch):
    _set_teacher_env(monkeypatch)
    monkeypatch.setenv("PRIVATESMS_INPUT_PRICE_PER_1M", "nan")
    with pytest.raises(synthetic.GenerationError, match="finite, non-negative"):
        synthetic._require_config()


def test_invalid_teacher_label_records_reported_usage_and_is_not_retried(monkeypatch, tmp_path):
    _set_teacher_env(monkeypatch)
    source = tmp_path / "public.tsv"
    source.write_text("0\t验证码提示样例\n", encoding="utf-8")
    output = tmp_path / "suggestions.jsonl"
    calls = []

    def invalid_response(*args, **kwargs):
        calls.append(1)
        return {"category": "unknown", "confidence": 0.5}, {"prompt_tokens": 100, "completion_tokens": 10}

    monkeypatch.setattr(assisted, "_request", invalid_response)
    options = dict(
        input_path=source,
        output_path=output,
        count=1,
        max_cost_usd=1,
        allow_remote=True,
        env_allow=True,
        confirm_public_egress=True,
        sleeper=lambda _: None,
    )
    with pytest.raises(GenerationError, match="unsupported category"):
        label_public_dataset(**options)
    usage_record = json.loads(output.read_text(encoding="utf-8"))
    assert usage_record["record_type"] == "usage"
    assert usage_record["provenance"]["status"] == "label_validation_rejected"
    assert usage_record["provenance"]["cost_usd"] > 0
    assert load_dataset(output)[0].texts == []

    resumed = label_public_dataset(**options)
    assert resumed["annotated_this_run"] == 0
    assert len(calls) == 1


def test_cli_refuses_public_labeling_input_outside_raw_directory(tmp_path, monkeypatch):
    source = tmp_path / "could-be-private.tsv"
    source.write_text("0\t短信样例\n", encoding="utf-8")
    monkeypatch.setattr("sys.argv", [
        "privatesms", "label-public", "--input", str(source), "--count", "1",
        "--allow-remote-labeling", "--confirm-public-data-egress", "--max-cost-usd", "1",
    ])
    monkeypatch.setenv("PRIVATESMS_ALLOW_PUBLIC_LABELING_API", "1")
    with pytest.raises(SystemExit):
        main()
