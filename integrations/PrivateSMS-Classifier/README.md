# PrivateSMS Classifier

Local-first Chinese SMS classification with a conservative review flow. This public snapshot includes source code and one INT8 six-class model. It contains no SMS training corpus, feedback database, evaluation rows, or private model artifacts.

## Included model

`models/rbt3-six-class/` is an INT8 ONNX fine-tune of [hfl/rbt3](https://huggingface.co/hfl/rbt3). Its fine-tuning corpus consisted of AI-generated synthetic SMS only. Real private SMS and feedback data were not used for this checkpoint. The training corpus is not part of this repository. See [the model card](docs/model-card.md) for provenance and limitations.

The model predicts `marketing`, `otp`, `personal`, `service`, `suspicious`, and `transaction`. Low-confidence results abstain to `uncertain`. Every result requires human review; this model is not validated for automatic blocking or production decisions.

## Run locally

Python 3.10+ is required. Install the CPU ONNX runtime and API dependencies:

```bash
python -m pip install -e '.[api,onnx]'
PRIVATESMS_MODEL_PATH=models/rbt3-six-class uvicorn privatesms.api.app:app --app-dir src --host 127.0.0.1 --port 8000 --no-access-log
```

Open `http://127.0.0.1:8000/test`. The page sends the text only to the local API; the application does not write classification requests to disk. Feedback endpoints are disabled until `PRIVATESMS_API_KEY` is configured. Protect the key and feedback database as private data.

For Docker, run `docker compose up --build`; the default bind address is loopback. Copy `.env.example` to `.env` only when configuration is needed. Do not expose the service to a public interface without adding suitable authentication and network controls.

## Training and data

Training commands accept local files supplied by the operator. This repository does not download, ship, or recreate the project’s private training corpora. Check the rights and privacy conditions for every dataset before using it. Keep data, reports containing row-level information, SQLite files, credentials, checkpoints, and training logs out of public commits. See [the release and data policy](docs/release-and-data-policy.md).

## License

The source and included fine-tuned model are offered under Apache License 2.0, subject to the upstream hfl/rbt3 terms and the provenance note in the model card. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
