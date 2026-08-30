# Merriv Roadmap

The roadmap is ordered by external interoperability, evidence integrity, and real
release workflows. It is directional rather than a delivery-date commitment.
Model Change Report 0.4.0 is frozen as the external-review baseline; new core
fields are not a progress metric.

## v0.1 — Evidence kernel and portable protocol

- [x] Content-addressed model snapshots and observation cache
- [x] Paired statistics, uncertainty-aware gates, and JSON/Markdown/JUnit/SARIF output
- [x] Recorded-output, ONNX Runtime, and OpenAI-compatible comparisons
- [x] Monotonic, sparse-audit, and exhaustive regression localization
- [x] Explicit adapter, metric, and executor plugin boundaries
- [x] ONNX semantic artifact diff and CPU per-tensor numerical diff
- [x] Authenticated cache envelopes, resource limits, and adversarial tests
- [x] Model Change Report 0.4 evidence, report, run, and target identities
- [x] Producer/consumer conformance fixtures with mandatory negative cases
- [x] Python, Node, and Rust content-identity vectors and Python/Rust interop
- [x] Repository-owned independent-style, Polygraphy-producer, and
  MLflow-consumer references (none count as external adoption)
- [x] First-mile `merriv import polygraphy` command over native or normalized evidence
- [x] in-toto predicate/Statement and local OCI 1.1 referrer-layout prototype
- [x] Machine-readable trust dimensions and explicit consumer-side authorization boundary
- [x] Reusable GitHub Action and SHA-pinned release automation
- [x] Checksums, SPDX SBOM, provenance attestations, and reproducibility checks

Exit criterion: a user can produce and independently verify a bounded release
decision without depending on Merriv internals at the protocol boundary.

## v0.2 — Target evidence and external interoperability

- [x] NVIDIA ModelOpt/TensorRT/Polygraphy reference vertical with exact artifacts,
  target evidence, quality gates, and first-bad-build localization
- [x] Indexed regression corpus with CPU and target-GPU cases
- Expand the corpus with independently reproduced quantization, opset, compiler,
  runtime, precision, tokenizer/config, and provider regressions
- Exercise Model Change Report producers and consumers maintained outside the core package
- Complete a registry round trip: push model, attach a signed Model Change Report referrer,
  discover, retrieve, authenticate, and verify without repository-local paths
- Compose Model Change Report references with retained SLSA provenance, OpenSSF Model Signing or
  Sigstore identity, and SPDX/CycloneDX ML-BOM instead of duplicating them
- Obtain a public design review of Model Change Report 0.4 from an external infra maintainer
- [x] Fix the public name as Merriv before distribution while retaining the
  `m2riv` package and wire namespaces for compatibility
- Add plugin conformance for manifests, mutation safety, secret canaries, and pairing
- Prototype a Ray or Kubernetes reference executor outside the core dependency set
- Define cancellation and failure semantics for external job schedulers
- Add adapter and metric capability negotiation
- Validate trusted publishing and reproducible builds across release hosts

Exit criterion: an independently reproduced target bundle and an external
producer/consumer pair pass the public conformance boundary.

## v0.3 — Integrations and release orchestration

- Registry promotion hooks that consume Model Change Reports rather than vendor-specific scores
- Reusable CI components beyond GitHub Actions
- Add importers only for retained evidence demanded by design partners; do not
  create a benchmark zoo or make Python Protocols the cross-language ABI
- Multi-candidate comparison and budget-aware staged evaluation
- Hardware/compiler regression evidence for GPU and NPU release workflows
- Benchmark snapshot latency, incremental hashing, cache hits, memory, package
  size, and retrieval at 1/10/50/100 GB without committing giant fixtures
- Add an OS-isolated ONNX/external-data inspector worker with strict path,
  digest, time, memory, and output boundaries
- Split report composition, evidence construction, and orchestration ownership
  before multiple core contributors need to edit the pipeline concurrently

Exit criterion: external systems can produce and consume the public Model Change
Report schema without depending on Merriv implementation details.

## Explicit non-goals

Merriv will not become a training framework, model registry, serving platform,
benchmark collection, web dashboard, or cluster scheduler. Those systems
integrate through adapters, executors, and Model Change Reports.

## Adoption scorecard

Repository-owned references are never counted in these numbers. The next
12-month success condition is three external organizations using Model Change
Reports on real
release work, not a star target.

| Signal | Current verified external count | 12-month target |
|---|---:|---:|
| Independent Model Change Report producers | 0 | 3 |
| Independent Model Change Report consumers | 0 | 3 |
| Organizations gating real releases | 0 | 3 |
| Independently reproduced regression cases | 0 | 3 |
| Upstream integrations maintained outside this repository | 0 | 1 |
| External maintainers | 0 | 1+ |

Foundation or neutral-home discussions start only after independent
implementations, organizations, and maintainers exist. Governance documents do
not substitute for those signals.
