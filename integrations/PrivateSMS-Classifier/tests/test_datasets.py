import pytest
import json

from privatesms.datasets import load_dataset, merge_datasets, prepare_dataset, prepare_training_data, redact_text, sanitize_public_dataset, split_by_template, template_split_report
from privatesms.datasets import loaders as dataset_loaders


def test_prepare_deduplicates_and_drops_conflicting_templates():
    data, report = prepare_dataset([
        ("验证码 123456", "ham"),
        ("验证码 123456", "ham"),
        ("验证码 654321", "spam"),
        ("你好", "ham"),
        ("", "spam"),
    ])
    assert report.exact_duplicates == 1
    assert report.empty_rows == 1
    assert report.conflicting_template_rows == 2
    assert data.texts == ["你好"]


def test_template_split_has_no_overlap_and_is_reproducible():
    rows = [(f"正常内容场景{chr(0x4e00 + i)}", "ham") for i in range(12)] + [(f"推广内容场景{chr(0x4e00 + i)}", "spam") for i in range(12)]
    data, _ = prepare_dataset(rows)
    first = split_by_template(data, seed=7)
    second = split_by_template(data, seed=7)
    assert first == second
    group_sets = {name: {data.template_ids[i] for i in indices} for name, indices in first.items()}
    assert not (group_sets["train"] & group_sets["validation"])
    assert not (group_sets["train"] & group_sets["test"])
    assert not (group_sets["validation"] & group_sets["test"])
    assert template_split_report(data, first) == {
        "template_groups": {name: len(groups) for name, groups in group_sets.items()},
        "overlap_groups": {"train_validation": 0, "train_test": 0, "validation_test": 0},
        "disjoint": True,
    }


def test_near_duplicate_texts_are_grouped_and_kept_in_one_split():
    rows = [
        ("【云信银行】您尾号1234的银行卡于10月15日消费268.00元，账户余额为9000.00元。如有疑问请拨打官方客服热线。", "ham"),
        ("【云信银行】您尾号5678的银行卡于10月16日消费168.00元，账户余额为8000.00元。如有疑问请拨打官方客服电话。", "ham"),
        ("周六一起吃饭", "ham"),
        ("家人已经到家", "ham"),
        ("明天记得带伞", "ham"),
        ("贷款广告立即申请", "spam"),
        ("中奖链接点击领取", "spam"),
        ("低息贷款联系办理", "spam"),
        ("会员促销限时优惠", "spam"),
    ]
    data, report = prepare_dataset(rows)
    assert report.near_duplicate_template_merges == 1
    near_indices = [index for index, text in enumerate(data.texts) if "云信银行" in text]
    assert len(near_indices) == 2
    assert data.template_ids[near_indices[0]] == data.template_ids[near_indices[1]]

    splits = split_by_template(data, seed=19)
    membership = {index: name for name, indices in splits.items() for index in indices}
    assert membership[near_indices[0]] == membership[near_indices[1]]


def test_near_duplicate_conflicting_labels_are_dropped_together():
    data, report = prepare_dataset([
        ("【云信银行】您尾号1234的银行卡于10月15日消费268.00元，账户余额为9000.00元。如有疑问请拨打官方客服热线。", "ham"),
        ("【云信银行】您尾号5678的银行卡于10月16日消费168.00元，账户余额为8000.00元。如有疑问请拨打官方客服电话。", "spam"),
    ])
    assert len(data) == 0
    assert report.near_duplicate_template_merges == 1
    assert report.conflicting_template_rows == 2


def test_merge_reports_global_near_duplicate_merges_once():
    messages = [
        "【云信银行】您尾号1234的银行卡于10月15日消费268.00元，账户余额为9000.00元。如有疑问请拨打官方客服热线。",
        "【云信银行】您尾号5678的银行卡于10月16日消费168.00元，账户余额为8000.00元。如有疑问请拨打官方客服电话。",
        "【云信银行】您尾号8888的银行卡于10月17日消费368.00元，账户余额为7000.00元。如有疑问请拨打官方客服热线。",
        "【云信银行】您尾号9999的银行卡于10月18日消费468.00元，账户余额为6000.00元。如有疑问请拨打官方客服电话。",
    ]
    one, one_report = prepare_dataset([(messages[0], "ham"), (messages[1], "ham")])
    two, two_report = prepare_dataset([(messages[2], "ham"), (messages[3], "ham")])
    assert one_report.near_duplicate_template_merges == 1
    assert two_report.near_duplicate_template_merges == 1

    merged, report = merge_datasets([(one, one_report), (two, two_report)])
    assert len({merged.template_ids[0], merged.template_ids[1]}) == 1
    assert report.near_duplicate_template_merges == 1


def test_unsupported_labels_are_rejected():
    with pytest.raises(ValueError):
        prepare_dataset([("x", "other")])


def test_tsv_quotes_do_not_merge_physical_sms_rows(tmp_path):
    path = tmp_path / "quoted.txt"
    path.write_text('0\t"短信第一行\n1\t促销第二行\n', encoding="utf-8")
    dataset, report = load_dataset(path)
    assert report.input_rows == 2
    assert len(dataset) == 2
    assert dataset.labels == ["ham", "spam"]


def test_csv_respects_quoted_commas(tmp_path):
    path = tmp_path / "quoted.csv"
    path.write_text('text,label\n"你好,朋友",0\n"推广,申请贷款",1\n', encoding="utf-8")
    dataset, report = load_dataset(path, text_column="text", label_column="label")
    assert report.input_rows == 2
    assert dataset.texts == ["你好,朋友", "推广,申请贷款"]


def test_merge_keeps_source_counts_and_deduplicates_across_files(tmp_path):
    one = tmp_path / "one.tsv"
    two = tmp_path / "two.tsv"
    one.write_text("0\t普通通知甲\n1\t营销通知乙\n", encoding="utf-8")
    two.write_text("0\t普通通知甲\n1\t营销通知丙\n", encoding="utf-8")
    merged, report = merge_datasets([load_dataset(one), load_dataset(two)])
    assert len(merged) == 3
    assert report.input_rows == 4
    assert report.exact_duplicates == 1


def test_merge_single_prepared_source_is_a_noop(monkeypatch):
    data, report = prepare_dataset([("普通通知", "ham"), ("广告推广", "spam")])

    def unexpected_rebuild(*args, **kwargs):
        raise AssertionError("single-source merge should not rebuild an already prepared dataset")

    monkeypatch.setattr(dataset_loaders, "prepare_dataset", unexpected_rebuild)
    merged, merged_report = merge_datasets([(data, report)])
    assert merged is data
    assert merged_report is report


def test_training_only_rows_never_enter_validation_or_test():
    public_rows = [(f"正常短信日常模板{chr(0x4e00+i)}", "ham", False, False) for i in range(12)]
    public_rows += [(f"垃圾短信营销模板{chr(0x4e00+i)}", "spam", False, False) for i in range(12)]
    teacher_rows = [(f"验证码合成模板{chr(0x4e00+i)}", "otp", True, True) for i in range(4)]
    dataset, report = prepare_dataset(public_rows + teacher_rows)
    splits = split_by_template(dataset, seed=13)
    synthetic_ids = {i for i, flag in enumerate(dataset.synthetic_flags) if flag}
    assert synthetic_ids <= set(splits["train"])
    assert not synthetic_ids.intersection(splits["validation"])
    assert not synthetic_ids.intersection(splits["test"])
    assert report.included_synthetic_rows == 4


def test_training_only_additions_do_not_change_public_holdout_and_collisions_are_dropped():
    public_rows = []
    for label in ("ham", "spam"):
        for i in range(30):
            public_rows.append((f"{label} 独立模板场景{chr(0x4e00 + i)}，这是用于验证固定公开数据拆分的短信正文。", label))
    public, public_report = prepare_dataset(public_rows)
    public_only, _, public_splits = prepare_training_data([(public, public_report)], seed=91)

    training, training_report = prepare_dataset([
        (public.texts[0], public.labels[0], True, True),
        ("【虚构平台】这是完全不同的合成风险提醒模板，编号九七三一，仅用于训练扩展。", "suspicious", True, True),
    ])
    combined, report, splits = prepare_training_data(
        [(public, public_report), (training, training_report)],
        seed=91,
    )

    def public_texts(dataset, indices):
        return [dataset.texts[i] for i in indices if not dataset.training_only[i]]

    assert public_texts(combined, splits["validation"]) == public_texts(public_only, public_splits["validation"])
    assert public_texts(combined, splits["test"]) == public_texts(public_only, public_splits["test"])
    assert public_texts(combined, splits["train"]) == public_texts(public_only, public_splits["train"])
    assert report.excluded_training_only_overlap_rows == 1
    assert report.included_synthetic_rows == 1
    assert all(combined.training_only[i] for i in splits["train"] if i >= len(public))
    assert template_split_report(combined, splits)["disjoint"]


def test_direct_template_split_keeps_public_holdout_and_omits_matching_supplements():
    rows = []
    for label in ("ham", "spam"):
        for i in range(30):
            rows.append((f"{label} 公共业务模板场景{chr(0x4e00 + i)}，该短信包含足够上下文供模板拆分验证，参考号{i}。", label))
    public, _ = prepare_dataset(rows)
    baseline_splits = split_by_template(public, seed=37)
    matched_text = public.texts[0]
    supplement_text = matched_text.replace("参考号0", "参考号999")
    combined, _ = prepare_dataset(rows + [(supplement_text, public.labels[0], True, True)])
    augmented_splits = split_by_template(combined, seed=37)

    def split_by_text(dataset, splits):
        return {
            name: [dataset.texts[i] for i in indices if not dataset.training_only[i]]
            for name, indices in splits.items()
        }

    assert split_by_text(public, baseline_splits) == split_by_text(combined, augmented_splits)
    supplement_index = combined.texts.index(supplement_text)
    public_group_split = next(
        name for name, indices in baseline_splits.items()
        if any(public.texts[i] == matched_text for i in indices)
    )
    assert (supplement_index in augmented_splits["train"]) is (public_group_split == "train")
    assert supplement_index not in augmented_splits["validation"]
    assert supplement_index not in augmented_splits["test"]


def test_jsonl_rejects_malformed_provenance_source(tmp_path):
    path = tmp_path / "bad-source.jsonl"
    path.write_text(json.dumps({"text": "短信样例", "label": "otp", "source": []}, ensure_ascii=False) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Unsupported record source"):
        load_dataset(path)


@pytest.mark.parametrize("verification", [None, False])
def test_jsonl_rejects_human_source_without_explicit_verification(tmp_path, verification):
    path = tmp_path / "unverified-human.jsonl"
    record = {"text": "短信样例", "label": "otp", "source": "human"}
    if verification is not None:
        record["human_verified"] = verification
    path.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="must explicitly set human_verified=true"):
        load_dataset(path)


def test_redact_text_masks_common_identifiers_but_keeps_short_codes():
    text, counts = redact_text(
        "验证码123456 https://example.com/a，联系13800138000 a@example.com "
        "身份证11010119900101123X 卡号6222021234567890123"
    )
    assert "123456" in text
    assert "<URL>" in text
    assert "<PHONE>" in text
    assert "<EMAIL>" in text
    assert "<ID>" in text
    assert "<ACCOUNT>" in text
    assert counts == {"url": 1, "email": 1, "id_number": 1, "bank_or_long_account": 1, "mobile": 1}


def test_sanitize_public_dataset_is_path_gated_private_and_provenance_tracked(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    raw = tmp_path / "data" / "raw"
    processed = tmp_path / "data" / "processed"
    raw.mkdir(parents=True)
    source = raw / "public.tsv"
    source.write_text(
        "0\t验证码123456，联系13800138000\n"
        "0\t验证码123456，联系13900139000\n"
        "1\t访问 https://example.com/a\n",
        encoding="utf-8",
    )
    output = processed / "clean.jsonl"

    with pytest.raises(ValueError, match="Confirm that the source is public"):
        sanitize_public_dataset(source, output, confirm_public_source=False)
    result = sanitize_public_dataset(source, output, confirm_public_source=True)

    records = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert result["output_rows"] == 2
    assert result["post_redaction_exact_duplicates_removed"] == 1
    assert result["redaction_counts"] == {"url": 1, "mobile": 1}
    assert records[0]["text"] == "验证码123456,联系<PHONE>"
    assert all(row["source"] == "public" and row["source_sha256"] == result["input_sha256"] for row in records)
    assert output.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        sanitize_public_dataset(source, output, confirm_public_source=True)


def test_sanitize_public_dataset_rejects_paths_outside_data_roots(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    outside = tmp_path / "outside.tsv"
    outside.write_text("0\t普通通知\n", encoding="utf-8")
    with pytest.raises(ValueError, match="under data/raw"):
        sanitize_public_dataset(outside, tmp_path / "data/processed/out.jsonl", confirm_public_source=True)
