# FP16-to-INT8 ONNX release regression

This is the deployment-side demo M2RIV is built for. It trains a small MLP on
scikit-learn's bundled copy of the real UCI handwritten-digits dataset, exports
the same learned weights as FP16 ONNX, creates three static INT8 QDQ builds with
ONNX Runtime, executes every build on CPU, applies paired confidence-interval
gates, and bisects the ordered build sequence.

The training split deliberately retains only one quarter of digit-1 examples.
This makes digit 1 a documented rare training class; labels and holdout examples
still come from the source dataset. The critical slice is declared from inputs as
digit 1 with normalized ink sum at least 18; it is not selected from model
outcomes. The regression is caused by an under-scaled calibration input range,
not by editing candidate predictions.

```console
python -m pip install -e ".[onnx-demo]"
python examples/onnx_quantization/run_demo.py --output runs/onnx-quantization
```

Inspect the actual deployment artifacts:

```console
m2riv artifact diff \
  runs/onnx-quantization/artifacts/build-00-fp16.onnx \
  runs/onnx-quantization/artifacts/build-02-int8-calibration-scale-075.onnx

m2riv artifact numerical-diff \
  runs/onnx-quantization/artifacts/build-00-fp16.onnx \
  runs/onnx-quantization/artifacts/build-02-int8-calibration-scale-075.onnx \
  --suite runs/onnx-quantization/suite.jsonl
```

Re-run localization from the generated gate statuses:

```console
m2riv bisect runs/onnx-quantization/checkpoints.jsonl --mode monotonic
```

Or ask M2RIV to execute only the checkpoints selected by the localization
strategy and emit an auditable report for each evaluation:

```console
m2riv bisect-run runs/onnx-quantization/artifact-checkpoints.jsonl \
  --adapter onnx \
  --suite runs/onnx-quantization/suite.jsonl \
  --policy runs/onnx-quantization/policy.yaml \
  --slice-key risk \
  --family cv \
  --output runs/onnx-bisect
```

Expected boundary:

```text
PASS build-00-fp16
PASS build-01-int8-balanced
BLOCK build-02-int8-calibration-scale-075  <-- first bad
BLOCK build-03-int8-calibration-scale-070
```

The demo is fully local after dependency installation. It downloads neither a
model nor a dataset, uses only `CPUExecutionProvider`, and writes the artifact
diff, compiled release plan, MCR, Markdown, JUnit, SARIF, and bisect evidence.
Each report also links a deduplicated evidence manifest instead of embedding the
same case references in every metric.

The `onnx-demo` extra pins the exact demo toolchain. Tested ONNX Runtime CPU
kernels can still place two common-class build-03 samples on opposite sides of
the argmax boundary (93.32–93.64% overall); the critical slice remains 78.72%,
the gate remains `BLOCK`, and the first bad build remains build-02. The generated
README and MCR are authoritative for the executing host. MCR execution records
now include the operating system, architecture, Python version, ONNX Runtime
version, device, and dtype. CI runs this demo on both Linux and Windows and keeps
the platform-specific bundles.

For scale-0.75, both observed platforms locate `hidden_linear` first. Exact
max-absolute-error / RMSE / cosine triples are themselves runtime evidence:

| Shared tensor | Linux x86-64 | Windows x86-64 |
| --- | ---: | ---: |
| `hidden_linear` | 3.8411 / 0.9126 / 0.997577 | 3.9343 / 0.9951 / 0.997173 |
| `hidden` | 12.4455 / 2.9291 / 0.863517 | 12.7547 / 2.9930 / 0.854680 |
| `output_linear` | 33.8709 / 7.5163 / 0.991185 | 34.0834 / 8.2349 / 0.990702 |
| `logits` | 33.9308 / 7.5554 / 0.991056 | 34.1688 / 8.2708 / 0.990609 |

Verify any generated report directory independently with:

```console
m2riv mcr verify runs/onnx-quantization/reports/build-02-int8-calibration-scale-075
```

Dataset provenance: [scikit-learn digits documentation](https://scikit-learn.org/stable/modules/generated/sklearn.datasets.load_digits.html)
and the [UCI Optical Recognition of Handwritten Digits dataset](https://archive.ics.uci.edu/dataset/80/optical+recognition+of+handwritten+digits).
