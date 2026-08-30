# Model Release Regression Corpus

This corpus indexes reproducible artifact-change failures and negative controls.
Each verified case binds a fixed reproduction entry point, expected release
semantics, and retained source fixtures. Generated run bundles are produced in CI
or locally and are not silently treated as committed evidence.

```console
python tools/verify_regression_corpus.py
```

The corpus contains two CI-exercised regression fixtures, one CI-verified negative
control, one target-observed ModelOpt/TensorRT regression, and one source-anchored
replay of a real llama.cpp regression. The ONNX and ModelOpt accuracy cases retain
real metric and artifact evidence, but their current non-zero-margin
matched-binary Holm profile returns `ERROR`; their historical BLOCK outcomes are
not promoted into current decisions. A historical replay is not a fresh upstream
binary execution, and target-observed is not independently reproduced. The
target is still ten independently reproduced real cases; planned cases do not
count. See [`backlog.md`](backlog.md).
