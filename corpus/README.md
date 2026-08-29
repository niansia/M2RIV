# Model Release Regression Corpus

This corpus indexes reproducible artifact-change failures and negative controls.
Each verified case binds a fixed reproduction entry point, expected release
semantics, and retained source fixtures. Generated run bundles are produced in CI
or locally and are not silently treated as committed evidence.

```console
python tools/verify_regression_corpus.py
```

The initial corpus contains two CI-verified regressions, one CI-verified negative
control, and one target-verified ModelOpt/TensorRT regression. Target-verified is
not the same as independently reproduced: the target is still ten independently
reproduced real cases, and planned cases do not count. See
[`backlog.md`](backlog.md).
