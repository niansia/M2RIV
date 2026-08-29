# ONNX opset-upgrade release evidence

This CPU-only example exercises a second artifact-change axis beyond quantization.
It converts the same ReLU graph from ONNX opset 17 to 18, records the structural
opset change, executes every shared tensor, and applies the normal release gate.

```bash
python examples/onnx_opset_upgrade/run_demo.py --output runs/onnx-opset-upgrade
```

Expected result:

```text
PASS: opset 17 -> 18; first numerical divergence = None
```

The report links both `artifact-diff.json` and `numerical-diff.json`. This is a
deliberately safe migration: M2RIV proves that the artifact changed and that the
declared cases remain numerically identical, rather than assuming either result.
