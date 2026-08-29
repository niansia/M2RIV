# M2RIV Roadmap

The roadmap is ordered by ecosystem leverage, not by feature count. Dates are not
promised before maintainers and users validate the preceding contracts.

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
- [x] Reusable GitHub Action for compare, verify, upload, and fail-closed status
- [x] Linux/Windows ONNX evidence matrix with runtime/platform provenance
- [x] Normative v1 content identity, Python/Node golden vectors, and a complete
  standard-library-only independent-producer conformance bundle
- [x] Composite-action end-to-end CI with a hash-locked dependency graph and
  explicit verifier completeness/coverage semantics
- [x] SHA-pinned CI and tagged builds with checksums, SBOM, and provenance

Exit criterion: a new user can produce a reviewable release decision locally or
against two endpoints in under ten minutes, and a plugin author can add a metric or
executor without changing kernel semantics.

## v0.2 — Reference distributed execution and ecosystem SDK

- TensorRT/ModelOpt reference vertical: engine metadata profile, compiler-build
  manifest, real GPU artifact sequence, numerical evidence, gate, and bisect
- Plugin conformance CLI with manifest, mutation, secret-canary, and pairing tests
- Reference Ray executor plugin outside the four-dependency kernel
- Kubernetes Job executor contract test kit and cancellation semantics
- Structured adapter/metric capability negotiation and unsupported-evidence errors
- PyPI Trusted Publisher configuration and independently verified reproducible builds

Exit criterion: two independent executor implementations pass the same conformance
suite and produce semantically equivalent MCRs from identical evidence.

## v0.3 — Integrations and release orchestration

- Registry promotion hooks that consume MCR rather than vendor-specific scores
- GitLab reusable CI component and richer policy-status annotations
- Import adapters for selected evaluation frameworks—without a benchmark zoo
- Multi-candidate comparison and budget-aware staged evaluation
- Hardware/compiler regression evidence for GPU/NPU release workflows

Exit criterion: at least three external systems produce or consume the public MCR
schema without depending on M2RIV internals.

## Explicit non-goals

M2RIV will not become a training framework, model registry, serving platform,
benchmark collection, web dashboard, or cluster scheduler. Those systems integrate
through adapters, executors, and MCR.
