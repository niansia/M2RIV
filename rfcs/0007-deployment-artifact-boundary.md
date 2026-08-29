# RFC 0007: Deployment artifact boundary

- Decision status: Accepted
- Implementation status: Implemented for v0.1
- Target: v0.1

## Decision

M2RIV's primary wedge is a deployable model artifact or ordered build sequence,
not a prompt, benchmark catalog, agent trace, or hosted evaluation dashboard.

Artifact inspection is a separate, inference-free evidence layer. An
`ArtifactProfile` records the artifact hash plus bounded semantic structure. An
`ArtifactDiff` compares profiles. A `ModelSnapshot` remains the execution identity
used by adapters and cache keys. Keeping these contracts separate prevents a
parser observation from silently becoming a behavioral or causal claim.

The first reference parser supports ONNX opsets, operator counts, initializer
dtypes, parameter counts, graph interfaces, quantization representation, external
tensor-data presence, and well-known config/tokenizer sidecar hashes. ONNX and
ONNX Runtime remain optional dependencies.

## Trust boundary

- Inspection never executes the graph and never loads external tensor data.
- File size and graph cardinalities are bounded.
- Files are hashed before and after ONNX parsing to detect concurrent mutation.
- The CPU adapter registers no custom-op library and refuses external tensor data.
- ONNX is a native parser/runtime boundary, not a sandbox. Untrusted artifacts
  still require a container, VM, or similarly isolated worker.

## Integration boundary

Promptfoo, DeepEval, Braintrust, Inspect AI, and other evaluators may produce
observations or metrics. ModelOpt, ONNX Runtime, TensorRT, compilers, and hardware
toolchains produce deployable candidates. M2RIV links those candidates to paired
evidence, release policy, MCR, and ordered-build regression localization.
