"""Real upstream ASGI + INT8 CPU model tests; isolated synthetic data only."""
import concurrent.futures
import json
import os
import secrets
import socket
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
CATEGORIES = {"personal", "otp", "service", "transaction", "marketing", "suspicious", "uncertain"}


def main():
    directory = Path(tempfile.mkdtemp(prefix="classifier-test-", dir=ROOT / "artifacts"))
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    key = secrets.token_urlsafe(32)
    env = dict(os.environ, PRIVATESMS_API_KEY=key, HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
    env.pop("PRIVATESMS_MODEL_PATH", None)
    env.pop("PRIVATESMS_DEFAULT_MODEL_PATH", None)
    env.pop("PRIVATESMS_MODEL_REGISTRY", None)
    database = directory / "feedback.sqlite3"
    log = (directory / "service.log").open("w", encoding="utf-8")
    process = subprocess.Popen([sys.executable, str(ROOT / "tools/windows_classifier.py"), "--port", str(port), "--feedback-db", str(database)],
                               cwd=ROOT, env=env, stdout=log, stderr=log,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    report = {"upstream_commit": "87f5874057f12756c7c5a0cc2544b04320fbf591", "checks": [], "synthetic_only": True}
    base = f"http://127.0.0.1:{port}"
    headers = {"X-API-Key": key}
    try:
        with httpx.Client(base_url=base, timeout=15) as client:
            for _ in range(120):
                if process.poll() is not None:
                    raise RuntimeError("upstream startup failed; see service.log")
                try:
                    health = client.get("/healthz")
                    if health.status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.25)
            else:
                raise RuntimeError("upstream startup timed out")
            model = health.json()["model_version"]
            assert model.endswith("-int8")

            def check(name, action):
                start = time.perf_counter()
                action()
                report["checks"].append({"name": name, "passed": True, "milliseconds": round((time.perf_counter()-start)*1000, 2)})
                print("PASS", name, flush=True)

            def post(route, payload, expected=200, auth=True):
                response = client.post(route, json=payload, headers=headers if auth else {})
                assert response.status_code == expected, (route, response.status_code, expected)
                return response.json()

            score_payload = {"address": "SYNTHETIC", "body": "【测试商店】周末优惠，退订回T。", "timestamp": 1000,
                             "localScore": 0, "threshold": 0.95, "profile": "conservative", "modelVersion": "caller-ignored"}

            def authorization():
                post("/api/v1/classify", {"text": "synthetic auth test"}, 401, False)
                post("/sms/score", score_payload, 401, False)
                assert client.get("/api/v1/feedback/pending").status_code == 401
                assert client.post("/api/v1/classify", json={"text": "synthetic"}, headers={"X-API-Key": "wrong"}).status_code == 401
            check("classification, score and feedback API authentication", authorization)

            samples = ["【测试银行】验证码123456，请勿泄露。", "【测试商店】周末限时优惠，退订回T。",
                       "测试提醒：包裹已送达驿站。", "合成通知：账户支出十元。", "合成个人消息：晚上一起吃饭吗？",
                       "虚构中奖通知：点击不可信链接领取礼物。", " ", "合成测试" * 1024]
            observations = []

            def classify_and_score():
                for text in samples:
                    c = post("/api/v1/classify", {"text": text, "sender": "SYNTHETIC"})
                    assert c["category"] in CATEGORIES and c["model_version"] == model
                    assert 0 <= c["confidence"] <= 1 and 0 <= c["spam_score"] <= 1
                    assert c["needs_review"] and not c["confidence_calibrated"]
                    d = post("/sms/score", dict(score_payload, body=text))
                    assert d["action"] == "allow" and d["needsReview"]
                    assert d["modelVersion"] == model and d["category"] == c["category"]
                    assert abs(d["score"]-c["spam_score"]) < 1e-6
                    observations.append({"category": c["category"], "review": c["needs_review"], "action": d["action"]})
            check("real INT8 classification and score agree, including 4096 Unicode characters", classify_and_score)
            report["model"] = model
            report["observations"] = observations

            def no_caller_override():
                for profile in ["strict", "balanced", "conservative"]:
                    for threshold in [0, 1]:
                        d = post("/sms/score", dict(score_payload, threshold=threshold, localScore=1, profile=profile, modelVersion="spoofed-model"))
                        assert d["action"] == "allow" and d["modelVersion"] == model
            check("caller scores, profiles and model names cannot override upstream review gate", no_caller_override)

            def validation_privacy():
                secret = "SYNTHETIC_PRIVATE_MARKER"
                for payload in [{"text": ""}, {"text": None}, {"text": secret*200}, {"text": "test", "sender": "x"*65}, {"text": "test", "unexpected": secret}]:
                    value = post("/api/v1/classify", payload, 422)
                    assert secret not in json.dumps(value)
                for fields in [{"timestamp": -1}, {"localScore": 2}, {"threshold": -1}, {"profile": "bad"}, {"modelVersion": ""}, {"body": ""}]:
                    post("/sms/score", dict(score_payload, **fields), 422)
                assert client.post("/api/v1/classify", content=b"{broken", headers={**headers, "Content-Type": "application/json"}).status_code == 422
            check("invalid and oversized payloads rejected without echoing submitted content", validation_privacy)

            def concurrent_inference():
                def infer(index):
                    start = time.perf_counter()
                    with httpx.Client(base_url=base, timeout=15, headers=headers) as concurrent_client:
                        c = concurrent_client.post("/api/v1/classify", json={"text": f"合成并发消息 {index}：验证码123456。"})
                        d = concurrent_client.post("/sms/score", json=score_payload)
                        assert c.status_code == 200 and d.status_code == 200 and d.json()["action"] == "allow"
                    return (time.perf_counter()-start)*1000
                with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                    timings = sorted(pool.map(infer, range(40)))
                report["concurrency"] = {"clients": 8, "message_pairs": 40, "requests": 80,
                    "p50_ms": round(statistics.median(timings), 2), "p95_ms": round(timings[37], 2),
                    "scope": "synthetic local classify+score pair, includes HTTP client creation, not production SMS latency"}
            check("8 concurrent clients / 80 actual model requests", concurrent_inference)

            def no_classification_persistence():
                with sqlite3.connect(database) as db:
                    assert db.execute("SELECT COUNT(*) FROM feedback").fetchone()[0] == 0
            check("classification and scoring do not write feedback records", no_classification_persistence)

            def feedback_review():
                payload = {"text": "合成纠错样本，不是私人短信", "feedback_type": "false_spam", "predicted_category": "marketing", "corrected_category": "otp", "model_version": model}
                post("/api/v1/feedback", payload, 401, False)
                post("/api/v1/feedback", dict(payload, corrected_category="marketing"), 422)
                created = post("/api/v1/feedback", payload, 202)
                feedback_id = created["feedback_id"]
                pending = client.get("/api/v1/feedback/pending", headers=headers).json()["items"]
                assert len(pending) == 1 and pending[0]["id"] == feedback_id
                route = f"/api/v1/feedback/{feedback_id}/review"
                post(route, {"decision": "approve"}, 422)
                assert post(route, {"decision": "approve", "category": "otp"})["status"] == "approved"
                post(route, {"decision": "reject"}, 404)
                assert not client.get("/api/v1/feedback/pending", headers=headers).json()["items"]
            check("official authenticated feedback, human review and no implicit training", feedback_review)
            def authenticated_relay():
                relay_env = dict(env, CLASSIFIER_URL=base, CLASSIFIER_API_KEY=key)
                completed = subprocess.run(["node", "tools/smoke_backend.mjs"], cwd=ROOT, env=relay_env,
                                           text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=90)
                (directory / "authenticated-relay.log").write_text(completed.stdout, encoding="utf-8")
                assert completed.returncode == 0, "authenticated relay smoke failed; see authenticated-relay.log"
            check("authenticated Go relay, 500-message real-model load, outage and restart recovery", authenticated_relay)
            report["passed"] = True
    except Exception as error:
        report["passed"] = False
        report["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill(); process.wait(timeout=5)
        log.close()
        (directory / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print("Report:", directory / "report.json", flush=True)


if __name__ == "__main__":
    main()
