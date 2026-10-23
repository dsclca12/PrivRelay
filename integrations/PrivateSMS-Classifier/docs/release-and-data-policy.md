# Public release and data policy

This repository is a public-safe source snapshot. It excludes all training SMS files, raw and processed data, feedback databases, evaluation rows, local experiment reports, private checkpoints, and credentials. The bundled model was selected from the project’s synthetic-only experiments.

When preparing a public change, inspect both the staged files and the complete commit history. Do not force-add files under local data or artifact directories. Avoid committing raw SMS, redacted SMS, labels tied to messages, template hashes derived from private text, message-level predictions, SQLite feedback stores, `.env` files, model checkpoints trained on private data, or reports that expose row-level details.

Dataset availability does not imply permission to redistribute or send data to an external labeling service. Review the source license, provenance, privacy conditions, and applicable provider terms before training or release.

PrivRelay feedback is never imported or trained automatically. For a training export, enable the explicit text inclusion consent in the PrivRelay console, then convert the downloaded JSON locally:

```bash
python scripts/import_privrelay_feedback.py feedback-export.json data/local/privrelay-feedback.jsonl --authorization-reference CONSENT-RECORD-ID
```

The converter requires a server-issued `export_id`/consent receipt for a training-purpose export with message text, rejects unsupported labels, removes sender and message identifiers, deduplicates identical text/label pairs, creates a mode-0600 training-only JSONL, and refuses to overwrite. `--authorization-reference` should point to the operator's separate record that authorizes training. The export ID can be reconciled with the server's encrypted audit record. No model is trained or uploaded by this command. The data remains sensitive SMS content: keep it out of source control and delete it when authorization is withdrawn. A server withdrawal prevents future exports but cannot recall files already downloaded or copied elsewhere.

The `.gitignore` excludes local data and experiment outputs. It is a safeguard, not a release audit: verify the final public tree and history before pushing.
