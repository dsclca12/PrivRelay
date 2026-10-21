# Public release checklist

This is a history-free release snapshot. Before publishing it: review the exact staged tree; keep this project’s private repository history separate; check provider/model terms for the synthetic data used to fine-tune the included checkpoint; and verify the checksum in `models/rbt3-six-class/SHA256SUMS`.

The included checkpoint uses AI-generated synthetic SMS only according to its recorded experiment provenance. It does not include the SMS corpus or per-message predictions. No real private SMS, user feedback, training corpus, or evaluation rows are shipped.

Do not add local `data/`, `artifacts/`, `.env`, SQLite files, per-message reports, or models trained with private real SMS when preparing later public commits. The model card records the limits of the included checkpoint.
