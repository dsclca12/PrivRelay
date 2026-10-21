import csv
import json

from privatesms.cli import _registry_version_for_artifact, main
from privatesms.datasets import prepare_dataset
from privatesms.evaluation.onnx_benchmark import _nearest_rank
from privatesms.training import train_baseline


def test_benchmark_cli_reports_runtime_without_sms_text(tmp_path, monkeypatch, capsys):
    rows = []
    for index in range(18):
        suffix = chr(0x4e00 + index)
        rows.append((f"朋友吃饭散步日常短信样本{suffix}", "ham"))
        rows.append((f"贷款促销申请点击链接推广样本{suffix}", "spam"))
    training_data, _ = prepare_dataset(rows)
    model_path = tmp_path / "baseline.joblib"
    train_baseline(training_data, model_path=model_path)

    heldout_path = tmp_path / "heldout.csv"
    private_marker = "私有样本不应写入报告"
    with heldout_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["text", "label"])
        writer.writeheader()
        writer.writerow({"text": f"{private_marker}日常朋友通知", "label": "ham"})
        writer.writerow({"text": "贷款优惠点击链接", "label": "spam"})

    report_path = tmp_path / "benchmark.json"
    monkeypatch.setattr("sys.argv", [
        "privatesms", "benchmark", "--model", str(model_path),
        "--input", str(heldout_path), "--text-column", "text", "--label-column", "label", "--threads", "1",
        "--latency-samples", "2", "--report", str(report_path),
    ])
    main()
    capsys.readouterr()

    report_text = report_path.read_text(encoding="utf-8")
    report = json.loads(report_text)
    assert report["test_data_policy"] == {"training_only_rows": 0, "synthetic_rows": 0, "samples": 2}
    assert report["latency_single_sample"]["samples"] == 2
    assert report["latency_single_sample"]["p50_ms"] >= 0
    assert report["process_peak_rss_kib"] > 0
    assert report["model_load_ms"] >= 0
    assert report["runtime"]["processor"]
    assert private_marker not in report_text


def test_nearest_rank_p95_uses_expected_rank():
    assert _nearest_rank(list(map(float, range(1, 21))), 0.95) == 19.0
    assert _nearest_rank([1.0], 0.95) == 1.0
    assert _nearest_rank([], 0.95) is None


def test_registry_model_artifact_reports_registry_version(tmp_path):
    artifact = tmp_path / "model_registry" / "versions" / "release-7" / "model.joblib"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"placeholder")

    assert _registry_version_for_artifact(artifact) == "release-7"
