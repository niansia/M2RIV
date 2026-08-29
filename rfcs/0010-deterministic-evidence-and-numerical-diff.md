# RFC 0010: Deterministic evidence identity and numerical artifact diff

- Decision status: Accepted
- Implementation status: Implemented for MCR 1.2
- Contract impact: Model Change Report 1.2; NumericalDiff 1.0

## Problem

MCR 1.1 hashed the entire report. Repeating the same artifact, suite, and policy
therefore produced a different ID because timestamps and wall-clock latency are
run observations. Gate findings also pointed at metric names but not directly at
the evidence sets that justified them. Structural artifact diff could locate the
first bad build without showing where executed values first diverged.

## Decision

MCR 1.2 separates two identities. `id` addresses replay-stable evidence: snapshot
IDs, the compiled release plan, evidence-scoped metrics, finding evidence links,
the evidence manifest, and supplemental artifact evidence. `run_id` addresses the
exact serialized execution, including timestamp, timing metrics, cache counts,
executors, limitations, and verdict.

Metric producers declare `identity_scope`. Quality metrics default to `evidence`;
the built-in wall-clock latency metric is `run`. Custom metrics that predate this
contract default to evidence scope for compatibility. Every metric gate finding
links to its metric evidence set. Critical-case findings receive a two-observation
set containing the baseline and candidate records for that case.

The ONNX numerical diff adds shared inferred tensors as temporary graph outputs,
executes both self-contained models with CPUExecutionProvider and optimizations
disabled, and aggregates max/mean absolute error, RMSE, relative error, cosine
similarity, and tolerance status. It reports the first divergent tensor in baseline
graph order and lists unmatched tensor names. It does not guess correspondences
when compiler or quantizer rewrites tensor names.

## Statistical semantics

`effect_size` is paired Cohen's dz: mean candidate-minus-baseline difference
divided by the sample standard deviation of paired differences. It is null for one
pair or a non-zero constant difference, where standardization is undefined. The
unstandardized engineering effect remains `effect` and MCR `delta`.

## Resource and trust boundary

Numerical diff inherits the ONNX parser limits, refuses external tensor data and
custom-op registration, uses only the CPU provider, bounds cases, tensors, and
elements, and removes temporary instrumented models. Native ONNX parsing and
execution are not a sandbox; untrusted artifacts still require OS isolation.

## Consequences

- Identical behavioral evidence can be deduplicated across reruns while each
  measured run remains independently addressable.
- A report consumer can follow every gate finding to concrete evidence without
  scanning metric records heuristically.
- Exact-name tensor matching is conservative. Rewritten graphs may expose partial
  coverage until a future source-map contract supplies trustworthy correspondence.
- MCR 1.1 consumers need a small migration for `run_id`, `identity_scope`, and
  finding `evidence_set_id`.
