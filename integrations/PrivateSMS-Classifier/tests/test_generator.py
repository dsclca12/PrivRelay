import inspect
import json

import pytest

from privatesms.datasets import load_dataset
from privatesms.generators import synthetic
from privatesms.generators.synthetic import GenerationError
from privatesms.labeling import validate_labeled_record


def _env(monkeypatch):
    monkeypatch.setenv("PRIVATESMS_TEACHER_BASE_URL", "https://teacher.example.invalid/v1")
    monkeypatch.setenv("PRIVATESMS_TEACHER_MODEL", "configured-model-id")
    monkeypatch.setenv("PRIVATESMS_TEACHER_API_KEY", "test-secret")
    monkeypatch.setenv("PRIVATESMS_INPUT_PRICE_PER_1M", "1")
    monkeypatch.setenv("PRIVATESMS_OUTPUT_PRICE_PER_1M", "2")


def test_default_off_and_no_free_text_input(monkeypatch, tmp_path):
    monkeypatch.setattr(synthetic, "_request", lambda *a, **k: pytest.fail("must not call network"))
    with pytest.raises(GenerationError):
        synthetic.generate_synthetic(count=1, output=tmp_path / "x.jsonl", max_cost_usd=1, allow_remote=False, env_allow=False)
    assert "text" not in inspect.signature(synthetic.generate_synthetic).parameters


def test_resume_provenance_and_synthetic_exclusion(monkeypatch, tmp_path):
    _env(monkeypatch)
    calls = []

    def fake_request(prompt, config, **kwargs):
        category = next(label for label in synthetic.CATEGORIES if f"目标类别只能是 {label}" in prompt)
        calls.append(category)
        text = "虚构账户登录验证码 482913，请勿转发。" if category == "otp" else f"这是虚构的{category}短信样例"
        return {"text": text, "category": category}, {"prompt_tokens": 100, "completion_tokens": 20}

    monkeypatch.setattr(synthetic, "_request", fake_request)
    output = tmp_path / "generated.jsonl"
    first = synthetic.generate_synthetic(count=2, output=output, max_cost_usd=1, allow_remote=True, env_allow=True, sleeper=lambda _: None)
    second = synthetic.generate_synthetic(count=2, output=output, max_cost_usd=1, allow_remote=True, env_allow=True, sleeper=lambda _: None)
    records = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert calls == ["personal", "otp"]
    assert first["completed_total"] == second["completed_total"] == 2
    assert all(r["synthetic"] and r["human_verified"] is False for r in records)
    assert all(r["provenance"]["prompt_tokens"] == 100 and r["provenance"]["cost_usd"] > 0 for r in records)
    excluded, report = load_dataset(output)
    included, included_report = load_dataset(output, include_synthetic=True)
    assert len(excluded) == 0 and report.excluded_synthetic_rows == 2
    assert len(included) == 2 and included_report.label_counts == {"personal": 1, "otp": 1}
    assert all(included.training_only)
    checked = validate_labeled_record(records[0])
    assert checked["human_verified"] is False


@pytest.mark.parametrize("url", ["https://example.com/x", "http://tinyurl.com/a"])
def test_real_and_shortened_urls_are_rejected(url):
    with pytest.raises(GenerationError):
        synthetic._validate_sample({"text": f"请查看{url}", "category": "suspicious"}, "suspicious")


def test_invalid_links_and_personal_identifiers_are_rejected_or_accepted():
    assert synthetic._validate_sample({"text": "请访问 https://sample.example.invalid/x", "category": "suspicious"}, "suspicious")
    for text in ("联系 13812345678", "身份证 11010519491231002X", "卡号 6222021234567890123"):
        with pytest.raises(GenerationError):
            synthetic._validate_sample({"text": text, "category": "uncertain"}, "uncertain")


def test_otp_samples_need_business_intent_after_code_normalization():
    generic = {"text": "验证码是482913，5分钟内有效，请勿告知他人。", "category": "otp"}
    with pytest.raises(GenerationError, match="specific business intent"):
        synthetic._validate_sample(generic, "otp")

    examples = (
        "登录验证码是482913，5分钟内有效。",
        "绑定新设备的身份核验码为731564。",
        "修改账户密码验证码：208745。",
        "虚构账户支付验证码 663902，请勿转发。",
    )
    for text in examples:
        assert synthetic._validate_sample({"text": text, "category": "otp"}, "otp") == text


def test_synthetic_prompt_requires_useful_otp_context(monkeypatch, tmp_path):
    _env(monkeypatch)
    monkeypatch.setattr(synthetic, "CATEGORIES", ("otp",))

    def inspect_prompt(prompt, config, **kwargs):
        assert "具体用途" in prompt
        assert "不要只生成验证码数字" in prompt
        return {"text": "虚构账户登录验证码 482913，请勿转发。", "category": "otp"}, {"prompt_tokens": 100, "completion_tokens": 20}

    monkeypatch.setattr(synthetic, "_request", inspect_prompt)
    synthetic.generate_synthetic(count=1, output=tmp_path / "otp-prompt.jsonl", max_cost_usd=1, allow_remote=True, env_allow=True, sleeper=lambda _: None)


def test_schema_never_accepts_teacher_output_as_human_verified():
    with pytest.raises(ValueError):
        validate_labeled_record({"text": "合成短信", "category": "otp", "source": "teacher_synthetic", "synthetic": True, "human_verified": True})


def test_schema_requires_explicit_human_verification():
    base = {"text": "人工核验短信", "category": "otp", "source": "human"}
    for record in (base, {**base, "human_verified": False}, {**base, "human_verified": "true"}):
        with pytest.raises(ValueError, match="human_verified"):
            validate_labeled_record(record)
    assert validate_labeled_record({**base, "human_verified": True})["human_verified"] is True


def test_cost_preflight_stops_before_network(monkeypatch, tmp_path):
    _env(monkeypatch)
    monkeypatch.setattr(synthetic, "_request", lambda *a, **k: pytest.fail("budget preflight should stop"))
    with pytest.raises(GenerationError, match="Cost budget reserve"):
        synthetic.generate_synthetic(count=1, output=tmp_path / "x.jsonl", max_cost_usd=0.000001, allow_remote=True, env_allow=True, sleeper=lambda _: None)


def test_openai_compatible_request_shape_and_usage(monkeypatch):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, size):
            payload = {"choices": [{"message": {"content": '{"text":"虚构短信样例","category":"otp"}'}}], "usage": {"prompt_tokens": 21, "completion_tokens": 12}}
            return json.dumps(payload).encode()

    class Opener:
        def open(self, request, timeout):
            assert request.full_url == "https://teacher.example.invalid/v1/chat/completions"
            assert request.get_header("Authorization") == "Bearer test-secret"
            body = json.loads(request.data)
            assert body["model"] == "configured-model-id"
            assert body["response_format"] == {"type": "json_object"}
            assert body["stream"] is False
            assert timeout > 0
            return Response()

    monkeypatch.setattr(synthetic.urllib.request, "build_opener", lambda *args: Opener())
    result, usage = synthetic._request("请输出 JSON", ("https://teacher.example.invalid/v1", "configured-model-id", "test-secret", 1.0, 2.0), sleeper=lambda _: None)
    assert result["category"] == "otp"
    assert usage == {"prompt_tokens": 21, "completion_tokens": 12}


def test_invalid_json_response_is_not_retried_and_usage_is_preserved(monkeypatch):
    calls = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, size):
            payload = {"choices": [{"message": {"content": "{invalid"}}], "usage": {"prompt_tokens": 50, "completion_tokens": 5}}
            return json.dumps(payload).encode()

    class Opener:
        def open(self, request, timeout):
            calls.append(1)
            return Response()

    monkeypatch.setattr(synthetic.urllib.request, "build_opener", lambda *args: Opener())
    with pytest.raises(synthetic.TeacherResponseError) as error:
        synthetic._request(
            "请输出 JSON",
            ("https://teacher.example.invalid/v1", "configured-model-id", "test-secret", 1.0, 2.0),
            retries=4,
            sleeper=lambda _: None,
        )
    assert len(calls) == 1
    assert error.value.usage == {"prompt_tokens": 50, "completion_tokens": 5}
