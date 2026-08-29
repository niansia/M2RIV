# NVIDIA ModelOpt to TensorRT live vertical

This is the target-GPU hero path. It exports reviewed fixed weights through a
PyTorch Conv1d graph, creates three INT8 artifacts with NVIDIA ModelOpt, builds
and executes TensorRT engines, compares every engine to its ONNX Runtime oracle
through Polygraphy, records latency and NVML process VRAM when available, applies
the rare-slice release gate, and bisects the ordered build sequence.

The source and execution environments are intentionally separate. Neither
ModelOpt nor TensorRT enters the four-dependency M2RIV kernel.

## 1. Build artifacts

```powershell
uv venv --python 3.11 .venv-modelopt
uv pip sync --python .venv-modelopt/Scripts/python.exe --require-hashes `
  examples/nvidia_tensorrt_vertical/requirements-modelopt.lock
.venv-modelopt/Scripts/python `
  examples/nvidia_tensorrt_vertical/build_artifacts.py `
  --fixture examples/onnx_quantization/assets/digits-mlp-fp32.onnx.b64 `
  --output runs/nvidia/artifact-inputs
```

The normal build is calibrated on 128 real training cases. Builds 02 and 03
scale only the declared calibration input to 0.65 and 0.60. Model weights and the
629-case stratified holdout remain unchanged.

## 2. Execute on GPU

```powershell
$env:UV_PROJECT_ENVIRONMENT = ".venv-tensorrt"
uv sync --frozen --extra onnx-demo
uv pip install --python .venv-tensorrt/Scripts/python.exe --no-deps `
  --require-hashes -r `
  examples/nvidia_tensorrt_vertical/requirements-tensorrt-cu125-windows.lock
.venv-tensorrt/Scripts/python `
  examples/nvidia_tensorrt_vertical/run_vertical.py `
  --artifacts runs/nvidia/artifact-inputs `
  --suite runs/onnx-quantization/suite.jsonl `
  --output runs/nvidia/live `
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
- opaque `ToolNativeEvidence` binding those exact bytes, runner names, and the
  Polygraphy CLI exit code;
- content-addressed `BackendComparisonEvidence` derived through Polygraphy's own
  `Comparator.compare_accuracy`, with per-output parity and a native-evidence link;
- snapshot manifests binding model/engine identities to retained bytes and build
  provenance binding source commit, tool versions, build parameters, calibration
  cohort, input artifact, and output snapshot;
- exact GPU, driver, TensorRT, Polygraphy, OS, Python, warmup, and case cohort;
- paired quality and latency MCR, strict verifier result, and release status;
- final monotonic bisect result;
- `target-evidence-manifest.json`, one root over every retained file and report.

Verify the archive root rather than checking only individual reports:

```console
m2riv mcr verify-target runs/nvidia/live
```

The command rejects a changed, missing, or extra retained file. It proves content
self-consistency, not authorship; publish the archive through a trusted CI
attestation when producer identity matters.

On Windows/WDDM, NVML may not expose process memory. In that case
`peak_vram_mib` is null and the limitation is explicit; it is never replaced by
zero. TensorRT engines are target/runtime-specific and must not be reused as
portable artifacts.

## Recorded reference execution

[`reference-receipt-rtx4060-20260829.json`](reference-receipt-rtx4060-20260829.json)
is the compact receipt from the first complete target execution. Its source
revision is `073d55b95116e5ef2f420de2e424d5d1c5c29061`; its target evidence ID is
`mcr:sha256:b2c99b902a6a09fba3cfd8aec7df78c18927ba7ebd7b8cf94596a8e63c125dbd`
and covers 4,514 retained files. The source `gpu-receipt.json` SHA-256 is
`a1ad352b7f01d47db2d35a4376f356327ae408277f510c5ccf3472e7dbaff1a3`;
the target manifest SHA-256 is
`7a1036ff5aa1541d82678bd3adb74c5160f58ba746c55336964b883c0a940186`.
The complete engines, Polygraphy outputs, and MCR bundles are distributed as a
separate [GitHub Release evidence archive](https://github.com/niansia/M2RIV/releases/tag/evidence-rtx4060-20260829)
because TensorRT engines are target-specific binaries.
`M2RIV-nvidia-evidence-RTX4060-MCR0.4-20260829.zip` has SHA-256
`06a060000afb40cd9dd6e529b08249863d20a91706030d2b505493572fd21a05`.
The compact receipt is a first-party observation, not independent reproduction.
