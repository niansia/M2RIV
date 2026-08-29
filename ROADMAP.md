# M2RIV Roadmap

The roadmap is ordered by ecosystem leverage, not by feature count. Dates are not
promised before maintainers and users validate the preceding contracts.

North-star metrics are external MCR producers, external MCR consumers, active
organizations, retained gate runs, and independently reproduced corpus cases.
Stars, package downloads, evaluator count, and core feature count are diagnostic
metrics only.

## v0.1 — Evidence kernel and vertical release path

- [x] Content-addressed model snapshots and observation cache
- [x] Paired statistics, uncertainty-aware gates, MCR JSON/Markdown/JUnit/SARIF
- [x] Recorded-output and OpenAI-compatible comparisons
- [x] Regression bisect with monotonic, sparse, and exhaustive modes
- [x] Explicit adapter/metric/executor plugin registry
- [x] Executor-aware cache identity and compiled release plans
- [x] ONNX semantic artifact diff and optional CPU Runtime adapter
- [x] Reproducible FP16-to-INT8 rare-slice gate and build bisect demo
- [x] Security/resource limits and adversarial regression suite
- [x] Execution-driven artifact bisect with per-checkpoint report bundles
- [x] Bounded MCR 1.3 manifests, stable/run identities, runtime provenance, and
  finding evidence links
- [x] CPU-only ONNX per-tensor numerical diff and opset-upgrade release example
- [x] Standalone MCR bundle verifier and external-producer conformance fixtures
- [x] First-class producer/consumer conformance commands, receipts, specification,
  compatibility matrix, and fail-closed decision profile
- [x] Polygraphy producer and MLflow consumer references outside the core package
- [x] Reusable GitHub Action for compare, verify, upload, and fail-closed status
- [x] Linux/Windows ONNX evidence matrix with runtime/platform provenance
- [x] Normative v1 content identity, 20 typed plus 1,024 binary64
  Python/Node/Rust golden vectors, two-way Python/Rust MCR interoperability, and
  a complete standard-library-only independent-producer conformance bundle
- [x] Composite-action end-to-end CI with a hash-locked dependency graph and
  explicit verifier completeness/coverage semantics
- [x] SHA-pinned CI and tagged builds with checksums, SBOM, and provenance

Exit criterion: a new user can produce a reviewable release decision locally or
against two endpoints in under ten minutes; an independent producer can pass the
MCR suite; and a consumer can preserve all decision states without importing the
M2RIV Python API.

## v0.2 — MCR adoption and NVIDIA artifact vertical

- [x] TensorRT/ModelOpt reference vertical: exact build manifest, real GPU execution,
  Polygraphy parity evidence, latency/VRAM boundary, quality gate, and bisect
- [x] Initial indexed regression corpus with CI cases and a target-GPU case
- Ten verified regression-corpus cases across quantization, opset, compiler,
  tactic/runtime, precision, tokenizer/config, and provider changes
- Two external MCR producers and two consumers maintained outside core
- Three design partners: LLM inference, CV/edge, and compiler/runtime
- Plugin conformance CLI with manifest, mutation, secret-canary, and pairing tests
- Reference Ray executor plugin outside the four-dependency kernel
- Kubernetes Job executor contract test kit and cancellation semantics
- Structured adapter/metric capability negotiation and unsupported-evidence errors
- PyPI Trusted Publisher configuration and independently verified reproducible builds

Exit criterion: at least one independently rerun NVIDIA GPU bundle, two
independent producers, two consumers, and three real CI design partners. A GPU
preflight skip or normalized fixture does not count.

## v0.3 — Integrations and release orchestration

- Registry promotion hooks that consume MCR rather than vendor-specific scores
- GitLab reusable CI component and richer policy-status annotations
- Import adapters for selected evaluation frameworks—without a benchmark zoo
- Multi-candidate comparison and budget-aware staged evaluation
- Hardware/compiler regression evidence for GPU/NPU release workflows

Exit criterion: at least three external systems produce or consume the public MCR
schema without depending on M2RIV internals.

## Six-month scorecard

| Metric | Month 0 | Month 3 target | Month 6 target |
|---|---:|---:|---:|
| External MCR producers | 0 | 1 | 3 |
| External MCR consumers | 0 | 1 | 3 |
| Active organizations with retained gate runs | 0 | 2 | 5 |
| Independently reproduced corpus cases | 0 | 3 | 10 |
| External `m2riv-*` maintainers unknown to the founder | 0 | 0 | 1 |
| Public issues/PRs requesting MCR in adjacent tools | 0 | 1 | 3 |

Repository-owned reference integrations are tracked separately and never counted
as external adoption.

## Explicit non-goals

M2RIV will not become a training framework, model registry, serving platform,
benchmark collection, web dashboard, or cluster scheduler. Those systems integrate
through adapters, executors, and MCR.
