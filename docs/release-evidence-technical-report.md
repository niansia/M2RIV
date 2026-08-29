# Release Evidence for Deployable AI Models

## A contract-based approach to artifact regression, statistical gating, and build localization

Status: M2RIV technical report, revision 2026-08-29

Scope: MCR 0.4 protocol candidate and M2RIV reference implementation

## Abstract

Deployable model releases cross optimizer, compiler, runtime, hardware, registry,
and CI boundaries. Native tools can produce excellent local answers while still
leaving organizations without a portable object that binds the exact artifacts,
evidence cohort, statistical interpretation, release policy, and first bad build.
M2RIV proposes the Model Change Report (MCR) as that vendor-neutral evidence
envelope. The reference implementation separates replay-stable evidence identity,
decision-bound report identity, and volatile run identity; requires fail-closed
PASS/WARN/BLOCK/ERROR semantics;
and supports producer and consumer conformance without importing M2RIV Python.

This report evaluates the approach with a CPU ONNX quantization regression, an
ONNX opset negative control, an independently implemented standard-library MCR
producer, a repository-owned Polygraphy producer and MLflow consumer, and a live
NVIDIA ModelOpt → TensorRT execution on an RTX 4060 Laptop GPU. In the live GPU
case, all four 629-case ONNX Runtime/TensorRT comparisons matched under the
declared tolerance, while a calibration-range change reduced the input-declared
critical slice from 91.49% to 78.72%. The gate returned PASS, PASS, BLOCK, BLOCK
and the ordered-build search localized build 02. This is exact first-party target
evidence, not an independent or cross-hardware performance claim.

## 1. Problem and boundary

MLflow already supports baseline-aware model validation; NVIDIA Polygraphy
already compares runner outputs; NVIDIA Model Optimizer already creates optimized
artifacts; TensorRT-Model-Connect already treats exact revision, target
compatibility, quality, and performance as separate validation layers. The open
question is therefore not whether evaluation or gating exists. It is whether
release evidence can cross these tools without collapsing into screenshots,
vendor-specific status fields, or unauditable prose.

MCR does not replace a producer's native oracle. It records the producer's exact
evidence and gives downstream CI, promotion, audit, and bisect systems shared
semantics. M2RIV is one reference producer, verifier, and conformance suite; the
CLI is optional at the protocol boundary.

## 2. Contract

An MCR binds:

- immutable baseline and candidate snapshot identities;
- executor/runtime/platform provenance;
- paired metrics, direction, sample size, uncertainty, and slice scope;
- a versioned release policy and explicit release authorization;
- content-addressed evidence-set and supplemental-evidence references;
- a replay-stable `evidence_id`, decision-bound report `id`, and volatile `run_id`;
- a bounded release plan and, when applicable, ordered-build localization.

`m2riv mcr verify --strict` rehashes every recognized local component and rejects
missing, traversing, symlinked, or identity-inconsistent evidence. It separately
reports bundle completeness, evidence-body coverage, observation verification,
and metric recomputability. A valid result means internal integrity; it does not
mean the producer is authentic. The verifier therefore reports
`authenticity_verified: false` and `trust_scope: self-consistency-only`.

## 3. Conformance

The normative producer profile contains fixed PASS, WARN, BLOCK, and ERROR bundles
plus four mandatory negative fixtures. A producer must match every semantic vector
and reject tampered identity, missing evidence, unknown version, and decision
mismatch. A consumer receipt preserves evidence/report identity and decision
status, and authorizes only PASS; WARN, BLOCK, and ERROR remain fail-closed.

```console
m2riv conformance producer examples/mcr_conformance
m2riv conformance consumer consumer-receipt.json --fixtures examples/mcr_conformance
```

The repository includes a standard-library-only independent producer, Python ↔
Rust MCR interoperability, typed Python/Node/Rust identity vectors, a Polygraphy
reference producer, and an MLflow reference consumer. These are implementation
evidence, not claims of external adoption or vendor endorsement.

## 4. Experimental design

The shared dataset is scikit-learn's bundled copy of the UCI handwritten-digits
data: 1,797 real observations, a fixed seed-23 stratified split, and 629 holdout
cases. The model weights are pinned by SHA-256. The critical slice is declared
from inputs before inference: digit 1 with normalized ink sum at least 18. The
holdout is unchanged between builds.

The deployment failure is a calibration configuration regression. Model weights
stay fixed while the first 128 training inputs used for INT8 calibration are
multiplied by 1.0, 0.65, or 0.60. The contracted calibration range creates overly
tight quantization scales. Policy evaluates overall accuracy with a 3% margin and
the critical slice with a 1.5% margin over paired evidence.

## 5. CPU ONNX case

The CPU hero path exports the fixed model to FP16 ONNX and creates QDQ INT8 builds
with ONNX Runtime. Linux and Windows CI retain separate evidence because numerical
diff magnitudes and latency are run-scoped. Across the bounded platform results,
the release story remains stable: baseline and balanced builds PASS; calibration-
contracted builds BLOCK; build 02 is first bad. A separate opset 17 → 18 control
changes artifact structure while preserving all declared shared tensors and emits
PASS. This prevents the corpus from equating every structural change with failure.

## 6. Live NVIDIA ModelOpt → TensorRT case

### 6.1 Exact cohort

The complete vertical ran locally on 2026-08-29 with:

- NVIDIA GeForce RTX 4060 Laptop GPU, 8,188 MiB;
- driver 555.97;
- TensorRT 10.4.0 and Polygraphy 0.53.4;
- Windows 10 build 26200, AMD64, Python 3.11.15;
- 629 holdout cases, three declared warmups;
- absolute tolerance 0.05 and relative tolerance 0.01.

The reviewed fixed MLP weights are exported through a mathematically equivalent
PyTorch Conv1d graph. ModelOpt 0.46 quantizes the Conv operators. The orchestrator
then builds target-specific TensorRT engines and asks Polygraphy to run ONNX
Runtime and TensorRT sequentially for every case. Polygraphy remains the backend
comparison oracle. M2RIV retains the opaque native RunResults and exit code,
derives its structured per-output verdict through Polygraphy's own Comparator API,
binds ONNX/engine bytes and build inputs, then applies release policy to the
TensorRT observations.

### 6.2 Results

| Build | Overall | Critical slice | Backend matches | Gate |
|---|---:|---:|---:|---|
| PyTorch-derived FP16 TensorRT | 94.75% | 91.49% | 629/629 | PASS |
| ModelOpt INT8 balanced | 94.91% | 91.49% | 629/629 | PASS |
| ModelOpt INT8 scale 0.65 | 93.32% | 78.72% | 629/629 | BLOCK |
| ModelOpt INT8 scale 0.60 | 92.85% | 74.47% | 629/629 | BLOCK |

Monotonic localization returned first bad index 2, `build-02-modelopt-int8-
scale-065`. Four strict MCR verifications succeeded. Every structured backend
claim links a verified native body and matching exit code; snapshot/build evidence
binds retained artifact bytes, source revision, calibration cohort, and tool
versions. A target evidence manifest covers every retained file and strict report.
The root is
`mcr:sha256:b2c99b902a6a09fba3cfd8aec7df78c18927ba7ebd7b8cf94596a8e63c125dbd`
over 4,514 retained files produced from source revision
`073d55b95116e5ef2f420de2e424d5d1c5c29061`. The complete archive SHA-256 is
`06a060000afb40cd9dd6e529b08249863d20a91706030d2b505493572fd21a05`.
The exact target-root, manifest, receipt, and archive digests are published with
the compact receipt.

The recorded single-case runner timings are retained as run evidence, but this
short execution does not establish a performance ranking. Windows/WDDM did not
expose per-process memory through NVML; `peak_vram_mib` is therefore null and its
measurement state is `unavailable`, never zero.

### 6.3 Compatibility observation

During development, an ONNX Runtime QDQ artifact with non-zero zero points was
rejected by TensorRT 10.4 because that parser required symmetric quantization for
the relevant path. This demonstrates why parser success, target compatibility,
quality, and performance must remain separate evidence claims. It is recorded as
a local observation rather than a corpus case until a bounded expected-failure
fixture and second target reproduction are retained.

## 7. Security and trust

The reference implementation treats local and remote evidence as potentially
hostile. Controls include bounded file, graph, tensor, JSON, and YAML structures;
safe YAML loading and alias limits; symlink and traversal refusal; custom-op and
ONNX external-data refusal in the reference runtime; metadata endpoint blocking;
secret canaries for remote responses; authenticated persistent cache envelopes;
atomic writes; explicit plugin registration; and fail-closed missing evidence.

HMAC protects a cache only from writers who do not possess the key. It does not
establish producer identity for an MCR. Trusted release pipelines still need
isolated runners, protected secrets/environments, immutable source revisions,
artifact attestations, and an organizational trust policy above self-consistency
verification.

## 8. Failure taxonomy and corpus

The indexed corpus begins with:

1. ONNX Runtime calibration-range rare-slice regression (CI verified);
2. ModelOpt/TensorRT calibration regression (target verified, not independent);
3. recorded-output rare-slice regression (CI verified);
4. ONNX opset structural negative control (CI verified).

Planned axes include TensorRT tactics and versions, precision overflow,
execution-provider changes, tokenizer/config sidecars, dynamic shapes, Jetson/DLA
compatibility, and non-monotonic compiler sequences. A planned case does not count
as verified; a repository-owned run does not count as external adoption.

## 9. Falsifiability and next work

The protocol thesis is weakened if design partners prefer vendor-native reports
and reject portable promotion semantics, or if an adjacent standard becomes the
accepted cross-tool contract. The next milestones are therefore not more
evaluators. They are an independently rerun NVIDIA bundle, external MCR producers
and consumers, three retained design-partner CI gates, and ten independently
reproduced corpus cases. North-star metrics explicitly exclude repository-owned
integrations from external adoption.

## References

- [MCR specification candidate](mcr-specification.md)
- [MCR conformance suite](mcr-conformance.md)
- [MLflow model evaluation and validation](https://mlflow.org/docs/latest/ml/evaluation)
- [MLflow validation implementation](https://mlflow.org/docs/latest/api_reference/_modules/mlflow/models/evaluation/validation.html)
- [NVIDIA Polygraphy comparator](https://docs.nvidia.com/deeplearning/tensorrt/latest/_static/polygraphy/comparator/toc.html)
- [NVIDIA Model Optimizer](https://github.com/NVIDIA/Model-Optimizer)
- [ModelOpt ONNX quantization API](https://nvidia.github.io/Model-Optimizer/reference/generated/modelopt.onnx.quantization.html)
- [TensorRT-Model-Connect validation and benchmark](https://nvidia.github.io/TensorRT-Model-Connect/user-guides/validate-benchmark/)
- [TensorRT-Model-Connect validation design](https://nvidia.github.io/TensorRT-Model-Connect/architecture/validation-design/)
