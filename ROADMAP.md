# M2RIV Roadmap

The roadmap is ordered by interoperability, evidence integrity, and real release
workflows. It is directional rather than a delivery-date commitment.

## v0.1 — Evidence kernel and portable protocol

- [x] Content-addressed model snapshots and observation cache
- [x] Paired statistics, uncertainty-aware gates, and JSON/Markdown/JUnit/SARIF output
- [x] Recorded-output, ONNX Runtime, and OpenAI-compatible comparisons
- [x] Monotonic, sparse-audit, and exhaustive regression localization
- [x] Explicit adapter, metric, and executor plugin boundaries
- [x] ONNX semantic artifact diff and CPU per-tensor numerical diff
- [x] Authenticated cache envelopes, resource limits, and adversarial tests
- [x] MCR 0.4 evidence, report, run, and target identities
- [x] Producer/consumer conformance fixtures with mandatory negative cases
- [x] Python, Node, and Rust content-identity vectors and Python/Rust interop
- [x] Independent-producer, Polygraphy-producer, and MLflow-consumer references
- [x] Reusable GitHub Action and SHA-pinned release automation
- [x] Checksums, SPDX SBOM, provenance attestations, and reproducibility checks

Exit criterion: a user can produce and independently verify a bounded release
decision without depending on M2RIV internals at the protocol boundary.

## v0.2 — Target evidence and external interoperability

- [x] NVIDIA ModelOpt/TensorRT/Polygraphy reference vertical with exact artifacts,
  target evidence, quality gates, and first-bad-build localization
- [x] Indexed regression corpus with CPU and target-GPU cases
- Expand the corpus with independently reproduced quantization, opset, compiler,
  runtime, precision, tokenizer/config, and provider regressions
- Exercise MCR producers and consumers maintained outside the core package
- Add plugin conformance for manifests, mutation safety, secret canaries, and pairing
- Add a reference remote executor without expanding the four-dependency kernel
- Define cancellation and failure semantics for external job schedulers
- Add adapter and metric capability negotiation
- Validate trusted publishing and reproducible builds across release hosts

Exit criterion: an independently reproduced target bundle and an external
producer/consumer pair pass the public conformance boundary.

## v0.3 — Integrations and release orchestration

- Registry promotion hooks that consume MCR rather than vendor-specific scores
- Reusable CI components beyond GitHub Actions
- Import adapters for selected evaluation frameworks without creating a benchmark zoo
- Multi-candidate comparison and budget-aware staged evaluation
- Hardware/compiler regression evidence for GPU and NPU release workflows

Exit criterion: external systems can produce and consume the public MCR schema
without depending on M2RIV implementation details.

## Explicit non-goals

M2RIV will not become a training framework, model registry, serving platform,
benchmark collection, web dashboard, or cluster scheduler. Those systems
integrate through adapters, executors, and MCR.
