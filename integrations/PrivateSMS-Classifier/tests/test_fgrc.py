import json
import stat
import zipfile

import pytest

from privatesms.datasets import import_fgrc_scd_sms, load_dataset


def _fixture_archive(path):
    rows = [
        {"文本": "无风险短信样例 甲", "案件编号": "case-1", "风险类别": "无风险"},
        {"文本": "物流客服诈骗样例 乙", "案件编号": "case-2", "风险类别": "冒充电商物流客服类"},
        {"文本": "投资诈骗短信样例 丙", "案件编号": "case-3", "风险类别": "虚假网络投资理财类"},
        {"文本": "投资诈骗短信样例 丁", "案件编号": "case-4", "风险类别": "虚假网络投资理财类"},
    ]
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("message/finetuning_initial.json", json.dumps(rows, ensure_ascii=False))


def test_fgrc_import_is_capped_seeded_and_training_only(tmp_path):
    archive = tmp_path / "source.zip"
    output = tmp_path / "processed" / "fgrc.jsonl"
    _fixture_archive(archive)

    summary = import_fgrc_scd_sms(archive, output, max_per_class=2, seed=7)
    rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    dataset, excluded_report = load_dataset(output)
    included, included_report = load_dataset(output, include_synthetic=True)

    assert summary["source_rows"] == 4
    assert summary["selected_rows"] == 3
    assert summary["mapped_label_counts"] == {"spam": 2, "ham": 1}
    assert summary["independent_test_eligible"] is False
    assert all(row["synthetic"] and row["training_only"] and row["source"] == "fgrc_synthetic" for row in rows)
    assert set(row["label"] for row in rows) == {"ham", "spam"}
    assert len(dataset) == 0 and excluded_report.excluded_synthetic_rows == 3
    assert len(included) == 3 and all(included.training_only) and all(included.synthetic_flags)
    assert included_report.included_training_only_rows == 3
    assert stat.S_IMODE(output.stat().st_mode) == 0o600


def test_fgrc_source_cannot_be_marked_as_ordinary_data(tmp_path):
    path = tmp_path / "invalid.jsonl"
    path.write_text(json.dumps({"text": "示例短信", "label": "spam", "source": "fgrc_synthetic"}) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="must be synthetic and training-only"):
        load_dataset(path, include_synthetic=True)


def test_fgrc_risk_only_mode_maps_fraud_to_suspicious_and_omits_no_risk(tmp_path):
    archive = tmp_path / "source.zip"
    output = tmp_path / "processed" / "fgrc-suspicious.jsonl"
    _fixture_archive(archive)

    summary = import_fgrc_scd_sms(
        archive,
        output,
        max_per_class=10,
        seed=7,
        risk_only_as_suspicious=True,
    )
    rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    loaded, report = load_dataset(output, include_synthetic=True)

    assert summary["mapping_mode"] == "risk_only_suspicious"
    assert summary["selected_rows"] == 3
    assert summary["mapped_label_counts"] == {"suspicious": 3}
    assert all(row["label"] == "suspicious" for row in rows)
    assert all(row["source_category"] != "无风险" for row in rows)
    assert all(row["synthetic"] and row["training_only"] for row in rows)
    assert len(loaded) == 3 and all(loaded.training_only) and all(loaded.synthetic_flags)
    assert report.included_synthetic_rows == report.included_training_only_rows == 3
