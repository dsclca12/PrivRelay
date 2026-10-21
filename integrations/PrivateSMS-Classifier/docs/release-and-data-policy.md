# Public release and data policy

This repository is a public-safe source snapshot. It excludes all training SMS files, raw and processed data, feedback databases, evaluation rows, local experiment reports, private checkpoints, and credentials. The bundled model was selected from the project’s synthetic-only experiments.

When preparing a public change, inspect both the staged files and the complete commit history. Do not force-add files under local data or artifact directories. Avoid committing raw SMS, redacted SMS, labels tied to messages, template hashes derived from private text, message-level predictions, SQLite feedback stores, `.env` files, model checkpoints trained on private data, or reports that expose row-level details.

Dataset availability does not imply permission to redistribute or send data to an external labeling service. Review the source license, provenance, privacy conditions, and applicable provider terms before training or release.

The `.gitignore` excludes local data and experiment outputs. It is a safeguard, not a release audit: verify the final public tree and history before pushing.
