# FP16-to-INT8 ONNX release regression

This is the deployment-side demo Merriv is built for. It uses a reviewed FP32
fixture from a small sklearn MLP trained on scikit-learn's bundled copy of the
real UCI handwritten-digits dataset, exports the same fixed weights as FP16 ONNX,
creates three static INT8 QDQ builds with ONNX Runtime, executes every build on
CPU, applies paired confidence-interval gates, and bisects the ordered sequence.

The fixture's training split deliberately retains only one quarter of digit-1
examples. This makes digit 1 a documented rare training class; labels and holdout
examples still come from the source dataset. The fixture is pinned by SHA-256 so
BLAS-specific training differences cannot silently change the artifact under
test. The critical slice is declared from inputs as digit 1 with normalized ink
sum at least 18; it is not selected from model outcomes. The regression is caused
by an under-scaled calibration input range, not by editing candidate predictions.

The retained evidence toolchain currently requires Python 3.11–3.13. Merriv's
base package supports Python 3.14, but the `onnx-demo` extra intentionally omits
these older retained dependencies on Python 3.14.

```console
uv sync --python 3.13 --frozen --extra onnx-demo
uv run --frozen python examples/onnx_quantization/run_demo.py --output runs/onnx-quantization
```

Inspect the actual deployment artifacts:

```console
merriv artifact diff \
  runs/onnx-quantization/artifacts/build-00-fp16.onnx \
  runs/onnx-quantization/artifacts/build-02-int8-calibration-scale-065.onnx

merriv artifact numerical-diff \
  runs/onnx-quantization/artifacts/build-00-fp16.onnx \
  runs/onnx-quantization/artifacts/build-02-int8-calibration-scale-065.onnx \
  --suite runs/onnx-quantization/suite.jsonl
```

Re-run localization from the generated gate statuses:

```console
merriv bisect runs/onnx-quantization/checkpoints.jsonl --mode monotonic
```

Or ask Merriv to execute only the checkpoints selected by the localization
strategy and emit an auditable report for each evaluation:

```console
merriv bisect-run runs/onnx-quantization/artifact-checkpoints.jsonl \
  --adapter onnx \
  --suite runs/onnx-quantization/suite.jsonl \
  --policy runs/onnx-quantization/policy.yaml \
  --slice-key risk \
  --family cv \
  --output runs/onnx-bisect
```

Expected platform-bounded decisions:

```text
PASS build-00-fp16
PASS build-01-int8-balanced
WARN or BLOCK build-02-int8-calibration-scale-065
WARN or BLOCK build-03-int8-calibration-scale-060
```

Both under-scaled builds fail closed, but platform- and runtime-specific INT8
kernels can leave their Holm-adjusted evidence inconclusive. The current pinned
Python 3.11 CI artifacts on Linux and Windows classify both as `WARN`;
localization therefore returns no first bad build and no PASS/BLOCK interval. If
build 03 is `BLOCK` while build 02 is `WARN`, the result is the build 01–03
uncertainty interval. Only a `BLOCK` at build 02 makes build 02 the conclusive
first bad build.

The demo is fully local after dependency installation. It downloads neither a
model nor a dataset, uses only `CPUExecutionProvider`, and writes the artifact
diff, compiled release plan, MCR, Markdown, JUnit, SARIF, and bisect evidence.
Each report also links a deduplicated evidence manifest instead of embedding the
same case references in every metric.

The `onnx-demo` extra pins the exact demo toolchain and the source fixture digest.
The generated README and MCR are authoritative for the executing host. MCR
execution records include the operating system, architecture, Python version,
ONNX Runtime version, device, and dtype. CI runs the demo on both Linux and
Windows, asserts bounded accuracy ranges plus the same fail-closed boundary, and
keeps both platform-specific evidence bundles. Exact max-absolute-error / RMSE /
cosine triples remain runtime evidence rather than copied documentation.

ONNX Runtime quantizer versions may retain the pre-QDQ name (`hidden_linear` or
`hidden_bias`) or expose the first common post-QDQ activation (`hidden`). The
verifier requires that the declared first divergence equal the first failed
tensor row and remain in this hidden-activation stage; it does not mistake a
tool-internal tensor rename for a changed release result.

Regenerating the training fixture is intentionally separate from running the
release demo. It may change floating-point weights across BLAS implementations,
so the new digest and both platform runs must be reviewed before committing it:

```console
python tools/regenerate_onnx_demo_fixture.py
```

Verify any generated report directory independently with:

```console
merriv mcr verify runs/onnx-quantization/reports/build-02-int8-calibration-scale-065
```

Dataset provenance: [scikit-learn digits documentation](https://scikit-learn.org/stable/modules/generated/sklearn.datasets.load_digits.html)
and the [UCI Optical Recognition of Handwritten Digits dataset](https://archive.ics.uci.edu/dataset/80/optical+recognition+of+handwritten+digits).
