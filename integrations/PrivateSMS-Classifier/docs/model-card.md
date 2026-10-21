# Model card: PrivateSMS RBT3 synthetic six-class preview

## Summary

This is an INT8 ONNX sequence classifier for six Chinese SMS intent/risk categories: `marketing`, `otp`, `personal`, `service`, `suspicious`, and `transaction`. It abstains to `uncertain` when the highest class score is below 0.60. All responses are marked for human review.

## Provenance

- Base checkpoint: [hfl/rbt3](https://huggingface.co/hfl/rbt3), which declares Apache-2.0.
- Fine-tuning data: AI-generated synthetic SMS only. The synthetic corpus is not distributed in this repository.
- Private real SMS, user feedback, and the project’s license-unresolved public SMS corpora were excluded from this checkpoint.
- No private SMS examples or row-level evaluation records are included in the model bundle.
- The synthetic examples were generated through OpenCode using third-party models. OpenCode’s terms assign output rights to the user, while also making third-party model terms applicable. Confirm the terms for the specific provider/model used before redistribution.

## Evaluation

An internal template-separated evaluation on 183 AI-generated SMS with human-checked labels reported 89.62% accuracy and 89.13% macro F1. This is a small synthetic-domain evaluation, not a natural-SMS benchmark. The class distribution and risk boundary performance are uneven; `suspicious` precision was 64.52%, and service recall was 76.60%.

The confidence temperature was fit on a small synthetic validation split. `confidence_calibrated` is deliberately false in this public bundle because calibration on synthetic messages does not establish calibration on natural messages.

## Intended use and limits

Use for local experimentation and human-reviewed triage. Do not use the model alone to block, delete, or suppress messages. It has not been validated on an independent natural-SMS test set, across providers, or for adversarial robustness. It may confuse routine service/transaction alerts with suspicious messages and may miss new fraud patterns.

## License

The fine-tuned weights are based on hfl/rbt3, declared Apache-2.0 by the upstream repository. This project distributes the fine-tuned checkpoint under Apache-2.0. See [NOTICE](../NOTICE). Third-party synthetic-output terms should be checked before downstream redistribution.
