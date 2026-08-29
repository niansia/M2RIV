# Polygraphy to MCR reference producer

This integration turns NVIDIA Polygraphy comparison results into paired,
case-level release evidence and then delegates policy, statistics, identity, and
MCR bundle creation to the public `m2riv` command. It lives outside
`src/m2riv`; Polygraphy and NumPy never become core dependencies.

```console
python integrations/polygraphy_mcr/produce.py \
  --polygraphy-results run-results.json \
  --baseline-runner onnxrt-runner \
  --candidate-runner trt-runner \
  --policy integrations/polygraphy_mcr/policy.yaml \
  --output runs/polygraphy-mcr
```

`run-results.json` must be a Polygraphy `RunResults.save()` artifact. The
integration uses Polygraphy's own `RunResults.load()` and
`Comparator.compare_accuracy()` APIs with the declared absolute and relative
tolerances. It preserves per-output match booleans in observation traces and
maps each iteration to one paired `match`/`mismatch` release case.

For CI and environments without TensorRT, `--normalized-results` accepts the
documented normalized interchange fixture. That route tests the MCR wiring, not
GPU execution. It must never be cited as TensorRT parity evidence.

The producer intentionally does not invent latency or GPU evidence. A GPU
vertical must attach the actual retained Polygraphy/TensorRT receipts and runtime
profile from the executing host.
