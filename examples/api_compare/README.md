# Compare two OpenAI-compatible endpoints

This example gates two chat-completions endpoints with the same paired suite. It
does not put API keys in a config file or command argument.

```console
export M2RIV_BASELINE_API_KEY=...
export M2RIV_CANDIDATE_API_KEY=...

m2riv compare-api https://baseline.example/v1 https://candidate.example/v1 \
  --baseline-model model-v1 \
  --candidate-model model-v2 \
  --baseline-revision deploy-v1 \
  --candidate-revision deploy-v2 \
  --suite examples/api_compare/suite.jsonl \
  --policy examples/api_compare/policy.yaml \
  --slice-key risk \
  --output runs/api-release
```

An unauthenticated local endpoint can omit the environment variables. The suite
uses exact-match outputs only as a canonical smoke test; projects should provide
domain metrics through the `PairedMetric` boundary.

Remote observations are cached only for this command invocation. Persistent reuse
is unsafe unless the deployment revision and non-secret credential scope are part
of model identity.

Exit code `0` is release-allowed, `2` is `BLOCK`, `3` means the evaluation was
invalid or incomplete, and `4` is a `WARN` not explicitly allowed by policy.
The release plan, evidence manifest, and all MCR/CI artifacts are written under
the output directory.
