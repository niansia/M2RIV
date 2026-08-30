# Release-evidence case study

## Artifact regression, statistical gating, and build localization

Status: reproducible first-party case study, revision 2026-08-30

Scope: Model Change Report 0.4 and the Merriv reference implementation

## Summary

Deployable model releases cross optimizer, compiler, runtime, hardware, registry,
and CI boundaries. Native tools can produce excellent local answers while still
leaving organizations without a portable object that binds the exact artifacts,
evidence cohort, statistical interpretation, release policy, and first bad build.
Merriv proposes the Model Change Report as that vendor-neutral evidence
envelope. The reference implementation separates replay-stable evidence identity,
decision-bound report identity, and volatile run identity; requires fail-closed
PASS/WARN/INSUFFICIENT_POWER/BLOCK/ERROR semantics;
and supports producer and consumer conformance without importing Merriv Python.

This case study exercises the approach with a CPU ONNX quantization regression, an
ONNX opset negative control, an independently implemented standard-library Model
Change Report
producer, a repository-owned Polygraphy producer and MLflow consumer, and a live
NVIDIA ModelOpt → TensorRT execution on an RTX 4060 Laptop GPU. In the live GPU
case, all four 629-case ONNX Runtime/TensorRT comparisons matched under the
declared tolerance, while a calibration-range change reduced the input-declared
critical slice from 91.49% to 78.72%. The archived pre-Holm gate returned PASS,
PASS, BLOCK, BLOCK and localized build 02. Merriv 0.1.0a3 re-evaluates the
retained paired observations with Tango score inference and returns WARN, WARN,
BLOCK, BLOCK. The historical first-bad claim does not transfer because the
reference-side endpoint is not a decisive PASS. This is exact first-party
target evidence, not an independent or cross-hardware performance claim.

## 1. Problem and boundary

MLflow already supports baseline-aware model validation; NVIDIA Polygraphy
already compares runner outputs; NVIDIA Model Optimizer already creates optimized
artifacts; TensorRT-Model-Connect already treats exact revision, target
compatibility, quality, and performance as separate validation layers. The open
question is therefore not whether evaluation or gating exists. It is whether
release evidence can cross these tools without collapsing into screenshots,
vendor-specific status fields, or unauditable prose.

The report does not replace a producer's native oracle. It records the producer's exact
evidence and gives downstream CI, promotion, audit, and bisect systems shared
semantics. Merriv is one reference producer, verifier, and conformance suite; the
CLI is optional at the protocol boundary.

## 2. Contract

A Model Change Report binds:

- immutable baseline and candidate snapshot identities;
- executor/runtime/platform provenance;
- paired metrics, direction, sample size, uncertainty, and slice scope;
- a versioned evaluation policy and explicit policy disposition;
- content-addressed evidence-set and supplemental-evidence references;
- a replay-stable `evidence_id`, decision-bound report `id`, and volatile `run_id`;
- a bounded release plan and, when applicable, ordered-build localization.

`merriv mcr verify --strict` rehashes every recognized local component and rejects
missing, traversing, symlinked, or identity-inconsistent evidence. It separately
reports bundle completeness, evidence-body coverage, observation verification,
and metric recomputability. A valid result means internal integrity; it does not
mean the producer is authentic. The verifier therefore reports
`authenticity_verified: false` and `trust_scope: self-consistency-only`, plus
separate machine-readable trust fields for retrievability, recomputability,
producer authentication, transparency verification, independent reproduction,
and deployment authorization.

## 3. Conformance

The normative producer profile contains fixed PASS, WARN, BLOCK, and ERROR bundles
plus four mandatory negative fixtures. A producer must match every semantic vector
and reject tampered identity, missing evidence, unknown version, and decision
mismatch. A consumer receipt preserves evidence/report identity and decision
status, and satisfies the fixed evaluation policy only on PASS; deployment
authorization remains a separate consumer-side decision.

```console
merriv conformance producer examples/mcr_conformance
merriv conformance consumer consumer-receipt.json --fixtures examples/mcr_conformance
```

The repository includes a standard-library-only independent producer, Python ↔
Rust Model Change Report interoperability, typed Python/Node/Rust identity
vectors, a Polygraphy
reference producer, and an MLflow reference consumer. These are implementation
evidence, not claims of external adoption or vendor endorsement.

## 4. Experimental design

The shared dataset is scikit-learn's bundled copy of the UCI handwritten-digits
data: 1,797 real observations, a fixed seed-23 stratified split, and 629 holdout
cases. The model weights are pinned by SHA-256. The current CPU ONNX critical
slice is declared from inputs before inference as normalized ink sum at least 19,
which yields 386 independent holdout cases. The frozen 2026-08-29 NVIDIA evidence
pack retains its original digit-1/high-ink cohort of 47 cases; that historical
evidence is not rewritten when the current demo policy changes. The holdout is
unchanged between builds.

The deployment failure is a calibration configuration regression. Model weights
stay fixed while the first 128 training inputs used for INT8 calibration are
multiplied by 1.0, 0.65, or 0.60. The contracted calibration range creates overly
tight quantization scales. The current CPU policy evaluates overall accuracy with
a 3% margin and the 386-case high-ink slice with a 1.5% margin over paired evidence.

## 5. CPU ONNX case

The CPU path exports the fixed model to FP16 ONNX and creates QDQ INT8 builds
with ONNX Runtime. Linux and Windows CI retain separate evidence because numerical
diff magnitudes and latency are run-scoped. The accuracy policy uses non-zero
margins over matched-binary outcomes. Tango score inference returns PASS for the
balanced INT8 candidate and BLOCK for both contracted-calibration candidates.
The FP16 self-check is PASS but is presented as the declared reference, not a
candidate gate. Localization identifies build 02 as the first bad build. A separate
opset 17 → 18 control explicitly selects an
interval-only policy, changes artifact structure while preserving all declared
shared tensors, and emits PASS. It is a structural and numerical negative
control, not a rejected zero-effect McNemar null. This prevents the corpus from
equating every structural change with failure.

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
comparison oracle. Merriv retains the opaque native RunResults and exit code,
derives its structured per-output verdict through Polygraphy's own Comparator API,
binds ONNX/engine bytes and build inputs, then applies release policy to the
TensorRT observations.

### 6.2 Results

| Build | Overall | Critical slice | Backend matches | Archived gate | Current 0.1.0a3 |
|---|---:|---:|---:|---|---|
| PyTorch-derived FP16 TensorRT | 94.75% | 91.49% | 629/629 | PASS | REFERENCE |
| ModelOpt INT8 balanced | 94.91% | 91.49% | 629/629 | PASS | WARN |
| ModelOpt INT8 scale 0.65 | 93.32% | 78.72% | 629/629 | BLOCK (pre-Holm) | BLOCK |
| ModelOpt INT8 scale 0.60 | 92.85% | 74.47% | 629/629 | BLOCK (pre-Holm) | BLOCK |

The archived monotonic localization returned first bad index 2,
`build-02-modelopt-int8-scale-065`. Re-evaluating the retained observations with
the current Tango score profile keeps builds 02 and 03 at BLOCK, but returns WARN
for the balanced candidate; no current onset or PASS/BLOCK interval is therefore
claimed. Four strict report verifications succeeded. Every structured backend
claim links a verified native body and matching exit code; snapshot/build evidence
binds retained artifact bytes, source revision, calibration cohort, and tool
versions. A target evidence manifest covers every retained file and strict report.
The root is
`mcr:sha256:b2c99b902a6a09fba3cfd8aec7df78c18927ba7ebd7b8cf94596a8e63c125dbd`
over 4,514 retained files produced from source revision
`073d55b95116e5ef2f420de2e424d5d1c5c29061`. The complete archive SHA-256 is
`06a060000afb40cd9dd6e529b08249863d20a91706030d2b505493572fd21a05`.
The [GitHub Release evidence pack](https://github.com/niansia/Merriv/releases/tag/evidence-rtx4060-20260829)
publishes the exact target root plus a separate checksum file; the repository
retains the compact receipt and reproduction source.

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
establish producer identity for a Model Change Report. Trusted release pipelines still need
isolated runners, protected secrets/environments, immutable source revisions,
artifact attestations, and an organizational trust policy above self-consistency
verification.

## 8. Failure taxonomy and corpus

The indexed corpus begins with:

1. ONNX Runtime calibration-range rare-slice regression (CI exercised; current
   formal gate returns `ERROR`);
2. ModelOpt/TensorRT calibration regression (target observed, not independent;
   current formal gate returns `ERROR`);
3. recorded-output rare-slice regression (CI-verified interval-only fixture);
4. ONNX opset structural negative control (CI-verified interval-only fixture).

Planned axes include TensorRT tactics and versions, precision overflow,
execution-provider changes, tokenizer/config sidecars, dynamic shapes, Jetson/DLA
compatibility, and non-monotonic compiler sequences. A planned case does not count
as verified; a repository-owned run does not count as external adoption.

## 9. Limitations and next validation

The target-GPU evidence is first-party and covers one hardware/software cohort.
The protocol still needs independent target reruns and producer/consumer
implementations maintained outside this repository. Repository-owned integrations
remain reference implementations and are not presented as external adoption.

## References

- [Model Change Report specification candidate](mcr-specification.md)
- [Model Change Report conformance suite](mcr-conformance.md)
- [MLflow model evaluation and validation](https://mlflow.org/docs/latest/ml/evaluation)
- [MLflow validation implementation](https://mlflow.org/docs/latest/api_reference/_modules/mlflow/models/evaluation/validation.html)
- [NVIDIA Polygraphy comparator](https://docs.nvidia.com/deeplearning/tensorrt/latest/_static/polygraphy/comparator/toc.html)
- [NVIDIA Model Optimizer](https://github.com/NVIDIA/Model-Optimizer)
- [ModelOpt ONNX quantization API](https://nvidia.github.io/Model-Optimizer/reference/generated/modelopt.onnx.quantization.html)
- [TensorRT-Model-Connect validation and benchmark](https://nvidia.github.io/TensorRT-Model-Connect/user-guides/validate-benchmark/)
- [TensorRT-Model-Connect validation design](https://nvidia.github.io/TensorRT-Model-Connect/architecture/validation-design/)
