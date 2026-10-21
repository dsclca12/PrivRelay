"""Run the pinned, unmodified PrivateSMS-Classifier ASGI application.

Windows requires Python 3.13+ (os.fchmod); use tools/start-classifier.ps1.
Classification, /sms/score, validation and feedback routes are all upstream code.
"""
import argparse
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=18788)
    parser.add_argument("--feedback-db", default="artifacts/classifier/feedback.sqlite3")
    args = parser.parse_args()
    if os.name == "nt" and not hasattr(os, "fchmod"):
        raise SystemExit("Use Python 3.13+ on Windows; upstream requires os.fchmod.")
    root = Path(__file__).resolve().parents[1]
    os.environ.setdefault("PRIVATESMS_MODEL_PATH", str(root / "integrations/PrivateSMS-Classifier/models/rbt3-six-class"))
    os.environ.setdefault("PRIVATESMS_FEEDBACK_DB", str(Path(args.feedback_db).resolve()))
    os.environ.setdefault("PRIVATESMS_INFERENCE_THREADS", "4")
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    import uvicorn
    uvicorn.run("privatesms.api.app:app", host="127.0.0.1", port=args.port, access_log=False)


if __name__ == "__main__":
    main()
