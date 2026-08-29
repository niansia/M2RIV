# NVIDIA ModelOpt to TensorRT live vertical

This is the target-GPU hero path. It exports reviewed fixed weights through a
PyTorch Conv1d graph, creates three INT8 artifacts with NVIDIA ModelOpt, builds
and executes TensorRT engines, compares every engine to its ONNX Runtime oracle
through Polygraphy, records latency and NVML process VRAM when available, applies
the rare-slice release gate, and bisects the ordered build sequence.

The source and execution environments are intentionally separate. Neither
ModelOpt nor TensorRT enters the four-dependency M2RIV kernel.

## 1. Build artifacts

```console
python -m venv .venv-modelopt
.venv-modelopt/Scripts/python -m pip install -r \
  examples/nvidia_tensorrt_vertical/requirements-modelopt.txt
.venv-modelopt/Scripts/python \
  examples/nvidia_tensorrt_vertical/build_artifacts.py \
  --fixture examples/onnx_quantization/assets/digits-mlp-fp32.onnx.b64 \
  --output runs/nvidia/artifact-inputs
```

The normal build is calibrated on 128 real training cases. Builds 02 and 03
scale only the declared calibration input to 0.65 and 0.60. Model weights and the
629-case stratified holdout remain unchanged.

## 2. Execute on GPU

```console
python -m venv .venv-tensorrt
.venv-tensorrt/Scripts/python -m pip install -e .
.venv-tensorrt/Scripts/python -m pip install -r \
  examples/nvidia_tensorrt_vertical/requirements-tensorrt-cu125-windows.txt
.venv-tensorrt/Scripts/python \
  examples/nvidia_tensorrt_vertical/run_vertical.py \
  --artifacts runs/nvidia/artifact-inputs \
  --suite runs/onnx-quantization/suite.jsonl \
  --output runs/nvidia/live \
  --polygraphy-command .venv-tensorrt/Scripts/polygraphy.exe
```

TensorRT's native parser may not accept non-ASCII artifact paths on Windows.
The orchestrator copies exact bytes into an ASCII temporary directory, then
copies engines and results back and rehashes them. This is a transport workaround,
not an identity change.

`--preflight` returns exit 3 if TensorRT, Polygraphy, `nvidia-smi`, or a usable GPU
cohort is absent. `--preflight --allow-missing` is only a contract smoke test; its
`ready: false` output is not GPU evidence.

## Evidence boundary

Every build retains:

- source ONNX and target-specific TensorRT engine;
- complete Polygraphy `RunResults` for ONNX Runtime and TensorRT;
- content-addressed `BackendComparisonEvidence` with per-output parity;
- exact GPU, driver, TensorRT, Polygraphy, OS, Python, warmup, and case cohort;
- paired quality and latency MCR, strict verifier result, and release status;
- final monotonic bisect result.

On Windows/WDDM, NVML may not expose process memory. In that case
`peak_vram_mib` is null and the limitation is explicit; it is never replaced by
zero. TensorRT engines are target/runtime-specific and must not be reused as
portable artifacts.

## Recorded reference execution

[`reference-receipt-rtx4060-20260829.json`](reference-receipt-rtx4060-20260829.json)
is the compact receipt from the first complete target execution. Its source
`gpu-receipt.json` SHA-256 is
`c3d70a68e5b9e544313808fe4832255791a9e38e135e691cf6f102ff6779490c`.
The complete engines, Polygraphy outputs, and MCR bundles are distributed as a
separate evidence archive because TensorRT engines are target-specific binaries.
The compact receipt is a first-party observation, not independent reproduction.
