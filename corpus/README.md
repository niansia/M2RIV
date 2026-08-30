# Model Release Regression Corpus

This corpus indexes reproducible artifact-change failures and negative controls.
Each verified case binds a fixed reproduction entry point, expected release
semantics, and retained source fixtures. Generated run bundles are produced in CI
or locally and are not silently treated as committed evidence.

```console
python tools/verify_regression_corpus.py
```

The corpus contains two CI-verified regressions, one CI-verified negative control,
one target-verified ModelOpt/TensorRT regression, and one source-anchored replay of
a real llama.cpp regression. A historical replay is not a fresh upstream binary
execution, and target-verified is not independently reproduced. The target is
still ten independently reproduced real cases; planned cases do not count. See
[`backlog.md`](backlog.md).
