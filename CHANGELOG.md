# Changelog

M2RIV follows semantic versioning for the Python package and explicit semantic
versions for portable JSON contracts. Pre-1.0 APIs may change with migration notes.

## Unreleased

### Added

- Strict content-addressed model/evidence contracts and exported JSON Schemas
- Paired runner, atomic cache, bootstrap/McNemar evidence, and four-state gates
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
- RFC 0012 canonical content-identity rules with stdlib Python/Node golden vectors
- A complete standard-library-only independent-producer MCR conformance bundle
- MCRVerification 1.1 integrity/completeness semantics and evidence coverage counts
- MCRVerification 1.2 explicit `self-consistency-only` trust scope and an
  `authenticity_verified` field that prevents integrity from implying provenance
- A CI smoke test that executes the local composite action and asserts its BLOCK
  output, uploaded bundle, and producer-neutral verification path

### Changed

- NumPy in the ONNX extras is capped below 2.3 so Python 3.11-targeted mypy can
  parse dependency stubs on every CI matrix runner
- `effect_size` now contains paired Cohen's dz when defined; raw change remains
  exclusively in `effect` / MCR `delta`
- The reusable action installs its dependency graph from a hash-locked export and
  reports one final exit code; verifier failures are canonical error code `3`
- `m2riv mcr verify --strict` now fails when any linked local evidence cannot be
  recognized and rehashed; the reusable action uses strict verification

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
  `M2RIV_CACHE_KEY` of at least 32 bytes
- The evidence kernel recomputes observation IDs and validates snapshot, case,
  seed, output digest, retention, and executor result cardinality before caching
- Strict JSON rejects duplicate keys, non-finite values, invalid Unicode, excessive
  nesting, and excessive node counts; YAML recursion failures become bounded input
  errors rather than tracebacks
- Case IDs reject control/bidirectional-override characters and excess length;
  JUnit output removes XML 1.0-invalid controls defensively
- Credential-bearing remote requests require HTTPS, cloud metadata link-local
  endpoints are blocked, redirect-enabled custom clients are refused, and response
  JSON is parsed with the same strict limits as local inputs
- ONNX inspection and execution consume the exact bounded bytes that were hashed,
  closing mutable-path and link-swap gaps; native ONNX remains a sandbox boundary
- Report output and verifier references reject links, junctions, special files,
  path escape, mutable reads, and redirected atomic-write targets
- CI runs a Python dependency vulnerability audit. Release build steps no longer
  receive an OIDC token; provenance is created in a separate attestation job
