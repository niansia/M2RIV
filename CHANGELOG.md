# Changelog

Merriv follows semantic versioning for the Python package and explicit semantic
versions for portable JSON contracts. Pre-1.0 APIs may change with migration notes.

## Unreleased

### Added

- Python 3.14 package support and CI coverage, plus Linux, Windows, and macOS
  package smoke tests
- GatePolicy 1.1 prospective standard-deviation inputs for planning-time MDE,
  with observed-design MDE retained only as diagnostic evidence
- Exact or Monte Carlo paired sign-randomization hypothesis evidence, while
  exact McNemar remains the zero-margin binary path
- Adversarial Holm tests for tied p-values, one-rule families, entirely
  underpowered families, complete declared-family semantics, and adjusted-p
  monotonicity
- Permanent GitHub Release creation with wheel, source distribution, SPDX SBOM,
  and checksums after a successful protected PyPI publish

### Changed

- The public quickstart installs immutable `merriv==0.1.0a2`; mutable `main`
  remains a development-only installation source
- The composite-action smoke test is a genuine PASS run and asserts exit code
  `0` without suppressing a deliberately failing step
- ONNX regression localization now claims a first bad build or PASS/BLOCK
  interval only when the observed gate endpoints establish one
- Statistical documentation now defines the complete declared Holm family,
  two-sided anomaly rationale, randomization assumptions, and the distinction
  between planned and observed-design MDE
- Matched-binary risk differences at non-zero margins no longer reuse the
  continuous sign-randomization test; formal Holm evaluation fails closed with
  `ERROR` until a dedicated binary non-inferiority method is selected
- Percentile-bootstrap intervals are explicitly documented as independent
  interval evidence, not confidence-set inversions of McNemar or randomization
  tests

### Security

- Tag builds fail before packaging when the tag and Python package version differ
- Release documentation now reflects the active protected Trusted Publisher path
  instead of describing publishing as disabled

## 0.1.0a2 - 2026-08-30

### Added

- MCR 0.4 fixed PASS/WARN/INSUFFICIENT_POWER/BLOCK/ERROR vectors and negative
  conformance fixtures
- Policy-family Holm-Bonferroni correction, declared family-wise alpha, target
  power, observed-design MDE, and fail-closed insufficient-power decisions
- A real llama.cpp #22544 historical regression replay with upstream issue, first
  bad commit, merged fix, and explicit replay limitations
- An in-toto v1 Statement schema and MCR predicate emitter for external attestors
- A complete unsigned in-toto Statement command and deterministic OCI 1.1
  subject/referrer layout for registry-client interoperability
- A packaged `merriv import polygraphy` first-mile command over native retained
  results or an explicitly non-live normalized interchange
- Machine-readable trust dimensions for integrity, completeness, retrievability,
  recomputability, producer authentication, transparency, independent
  reproduction, and consumer-side deployment authorization
- Tool-native opaque evidence, snapshot-to-artifact bindings, build provenance,
  and a complete target evidence manifest
- Separate bundle completeness, evidence-body coverage, observation verification,
  and metric recomputability results

- Strict content-addressed model/evidence contracts and exported JSON Schemas
- Paired runner, atomic cache, bootstrap/McNemar evidence, and five-state gates
- MCR JSON, Markdown, JUnit, SARIF, and compiled release-plan bundles
- Explicit dispatched, returned, and content-addressed cache-hit provenance in MCRs
- Recorded-output and bounded OpenAI-compatible adapters
- Monotonic, sparse, and exhaustive checkpoint regression localization
- Explicit adapter/metric/executor plugin registry and local executor
- Content-addressed preflight plans including statistical/runtime identity
- Bounded ONNX artifact profiles and semantic diffs for opsets, operators,
  dtypes, graph interfaces, sidecars, and quantization representation
- Optional CPU-only ONNX Runtime adapter and reproducible FP16-to-INT8 release demo
- Execution-driven recorded/ONNX bisect with a full report for every evaluated
  checkpoint and a strict artifact-only manifest
- MCR 1.1 external evidence manifests and reusable content-addressed evidence sets
- MCR 1.2 deterministic evidence IDs, exact run IDs, run-scoped metrics, and
  direct finding-to-evidence-set references
- MCR 1.3 execution runtime/platform provenance and a standalone bundle verifier
  that rehashes reports, manifests, sets, plans, and known supplemental evidence
- Minimal external-producer PASS/WARN/BLOCK conformance fixtures and a reusable
  GitHub Action that compares, verifies, uploads, then enforces the decision
- Linux/Windows ONNX evidence jobs and platform-labeled numerical-diff examples
- A brand-gated, protected-environment PyPI Trusted Publishing job plus public
  release/security owner checklist
- Bounded CPU-only ONNX per-tensor numerical diff with first-divergence reporting
- A second CPU-only artifact axis that verifies an opset 17-to-18 migration
- SHA-pinned CI plus tag builds with SHA-256 checksums, SPDX SBOM, and signed
  GitHub artifact provenance
- Purple-team parser, cache, network, CI-renderer, plugin, and bisect controls
- RFC 0012 canonical content-identity rules with 20 typed and 1,024 binary64
  Python/Node/Rust golden vectors plus bidirectional Python/Rust MCR verification
- A complete standard-library-only independent-producer MCR conformance bundle
- MCRVerification 1.1 integrity/completeness semantics and evidence coverage counts
- MCRVerification 1.2 explicit `self-consistency-only` trust scope and an
  `authenticity_verified` field that prevents integrity from implying provenance
- A release-time CI smoke test that executes the local composite action, exercises
  BLOCK enforcement, uploads the bundle, and verifies the producer-neutral path
- First-class producer and consumer conformance commands, normative
  PASS/WARN/BLOCK profiles, deterministic receipts, a compatibility matrix, and
  self-certification rules
- Repository-owned Polygraphy producer and MLflow consumer reference integrations
  that remain outside the four-dependency evidence kernel
- Content-addressed `BackendComparisonEvidence` with strict bundle verification
  for retained external backend parity and runtime measurements
- A live NVIDIA ModelOpt-to-TensorRT vertical with exact GPU/software provenance,
  Polygraphy parity, quality gate, ordered-build localization, and a manual
  target-runner workflow
- An indexed regression corpus that distinguishes CI verification, target-only
  verification, and independent reproduction
- A public release-evidence architecture diagram and reproducible case study
- A source-first quickstart, concise repository entry page, and citation metadata
- Three new public schemas for backend evidence and producer/consumer conformance,
  bringing the exported public surface to 24 contracts
- Five target/provenance schemas plus expanded verification contracts, and an
  OCI MCR artifact manifest, bringing the exported public surface to 31 contracts

### Changed

- The public name, Python distribution, import namespace, and executable are
  unified as `merriv`; brand-neutral `mcr:` wire identifiers remain stable.
- Public prose spells out Model Change Report; `MCR` remains only where it is a
  versioned technical identifier, filename, schema name, or CLI command group.
- CI and release builds now install from the frozen `uv.lock` rather than
  resolving development and build dependencies from floating ranges
- Release builds disable shared dependency caches, and Dependabot updates use a
  seven-day cooldown to reduce cache-poisoning and just-published-package risk
- The exact build backend is hash-locked and preinstalled; package and composite
  action builds disable network-resolved build isolation
- The pre-alpha portable envelope is now MCR 0.4.0: content IDs and hash domains
  use the brand-neutral `mcr:` namespace, the canonical report filename is
  `mcr-report.json`, and normative schemas live in `schemas/mcr-0.4`
- MCR now separates replay-stable `evidence_id`, decision-bound report `id`, and
  exact execution `run_id`; opposite verdicts cannot share a report identity

- NumPy in the ONNX extras is capped below 2.3 so Python 3.11-targeted mypy can
  parse dependency stubs on every CI matrix runner
- `effect_size` now contains paired Cohen's dz when defined; raw change remains
  exclusively in `effect` / MCR `delta`
- The reusable action installs its dependency graph from a hash-locked export and
  reports one final exit code; verifier failures are canonical error code `3`
- `merriv mcr verify --strict` now fails when any linked local evidence cannot be
  recognized and rehashed; the reusable action uses strict verification
- Project positioning now treats Model Change Report as the protocol candidate
  and Merriv as its reference implementation, with deployment artifact evidence
  as the first wedge
- MCR 0.4 `decision.allowed` is now consistently presented as “evaluation policy
  satisfied”; CLI, Markdown, SARIF, conformance, and MLflow output explicitly
  leave deployment authorization to the consumer
- MCR 0.4.0 is frozen as the external-review envelope; future semantic or identity
  changes require a new envelope version rather than in-place edits

### Security

- The development lock requires pytest 9.0.3 or newer to exclude the vulnerable
  temporary-directory handling range reported by GitHub Dependabot
- Remote observations default to ephemeral cache unless deployment identity is
  explicit
- Credentials and secret-bearing config fields are excluded from persistent
  identity and output surfaces
- Input, response, retry, time, cache, plugin, and plan cardinality limits fail
  closed
- ONNX execution refuses external tensor data and never registers custom-op
  libraries; native parsing remains an explicit isolation boundary
- `WARN` fails closed unless the policy explicitly sets `allow_warn: true`
- Artifact hashing and discovery enforce total-byte, per-file, and traversal budgets
- Cache format v2 authenticates every observation envelope with HMAC-SHA-256.
  The default key is run-local; intentional shared reuse requires a secret
  `MERRIV_CACHE_KEY` of at least 32 bytes
- The evidence kernel recomputes observation IDs and validates snapshot, case,
  seed, output digest, retention, and executor result cardinality before caching
- Strict JSON rejects duplicate keys, non-finite values, invalid Unicode, excessive
  nesting, and excessive node counts; YAML recursion failures become bounded input
  errors rather than tracebacks
- Case IDs reject control/bidirectional-override characters and excess length;
  JUnit output removes XML 1.0-invalid controls defensively
- Credential-bearing remote requests require HTTPS; cloud metadata hostnames,
  link-local endpoints, and known non-link-local addresses such as
  `100.100.100.200` are blocked; redirect-enabled custom clients are refused, and
  response JSON is parsed with the same strict limits as local inputs
- ONNX inspection and execution consume the exact bounded bytes that were hashed,
  closing mutable-path and link-swap gaps; native ONNX remains a sandbox boundary
- Report output and verifier references reject links, junctions, special files,
  path escape, mutable reads, and redirected atomic-write targets
- CI runs a Python dependency vulnerability audit. Release build steps no longer
  receive an OIDC token; provenance is created in a separate attestation job
- CI upgrades the hosted runner's packaging bootstrap to `setuptools>=83` before
  auditing, excluding PYSEC-2026-3447 from the executable build environment
