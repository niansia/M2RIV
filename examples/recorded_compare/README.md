# Recorded-output release gate

This offline example represents a model converted from FP16 to INT4. Overall
accuracy changes by only 10%, while both low-light rare-class cases regress. The
release policy blocks the candidate on that slice.

```console
merriv compare \
  examples/recorded_compare/baseline.jsonl \
  examples/recorded_compare/candidate.jsonl \
  --suite examples/recorded_compare/suite.jsonl \
  --policy examples/recorded_compare/policy.yaml \
  --slice-key frequency \
  --output runs/recorded-example
```

Expected exit code: `2` (`BLOCK`). Generated artifacts:

- `release-plan.json` - content-addressed policy/suite/metric/statistical preflight;
- `evidence-manifest.json` - deduplicated content-addressed case evidence;
- `mcr-report.json` - canonical Model Change Report;
- `summary.md` - human review artifact and GitHub Step Summary format;
- `junit.xml` - test UI integration;
- `results.sarif` - code scanning integration.

In CI, run the same command as a release stage. Exit `0` means release-allowed
PASS (or a WARN explicitly allowed by policy), `2` means a policy-backed BLOCK,
`3` means the evaluation was invalid or could not run, and `4` means a fail-closed
WARN. A broken or inconclusive evaluation is never represented as PASS.
