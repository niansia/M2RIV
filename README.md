# M2RIV

**Model-to-Release Inspection & Verification** *(pre-alpha working name)*

M2RIV is an open-source release gate for **deployable model artifacts**. It
compares a candidate quantized, compiled, converted, or runtime-specific build
against its baseline; inspects what changed inside the artifact; measures paired
regressions with confidence intervals; and bisects the build sequence that
introduced a failure.

> Every model change should be reviewable before it ships.

## Why this exists

Promptfoo, DeepEval/Confident AI, Braintrust, and Inspect AI already provide strong
application, agent, safety, and LLM-evaluation workflows. M2RIV does not claim
that CI evaluation or release gating is empty territory. Its narrower target is
the deployment build itself: FP16 vs INT8, ONNX opset changes, compiler revisions,
runtime/provider changes, and later TensorRT/NPU/hardware builds.

If the thing under test is a prompt, RAG application, or agent trajectory, start
with those evaluation tools. If the event under review is a model artifact being
quantized or compiled for deployment, M2RIV is intended to preserve artifact
provenance, paired statistical evidence, gate semantics, and regression onset in
one portable Model Change Report. See the source-linked
[competitive boundary](docs/competitive-landscape.md).

The project is deliberately local-first and provider-agnostic. It does not train
models, replace registries, or become a benchmark zoo.
The base install remains four runtime dependencies (`httpx`, `pydantic`, `PyYAML`,
and `typer`); ONNX and demo tooling are optional extras.

## What works now

The first foundation slice provides:

- strict, versioned contracts for model references, snapshots, evaluation cases,
  observations, evidence, claims, and run manifests;
- content identity for local files and directories, independent of their location;
- bounded ONNX artifact inspection and semantic diff for opsets, operators,
  initializer dtypes, graph interfaces, parameter counts, and sidecar hashes;
- CPU-only per-tensor numerical diff that locates the first shared activation
  whose values exceed explicit absolute/relative tolerances;
- domain-separated fingerprints for execution-relevant configuration;
- a CLI for inspecting artifacts, compiling release plans, and exporting schemas;
- a strict paired runner with kernel-owned observation identity and authenticated,
  atomic case-level caching;
- pluggable paired metrics with explicit units and optimization direction;
- explicit plugin manifests/registry without automatic untrusted-code loading;
- executor-aware cache identity for local, Ray, Kubernetes, or custom fabrics;
- content-addressed preflight plans that bind policy rules before inference;
- deterministic paired bootstrap statistics, binary flip evidence, and exact
  McNemar evidence;
- uncertainty-aware `PASS` / `WARN` / `BLOCK` / `ERROR` release gates;
- a bounded OpenAI-compatible endpoint adapter with secret-safe provenance;
- an optional CPU-only ONNX Runtime adapter that refuses external tensor data and
  never loads custom-op libraries;
- monotonic, sparse-audit, and exhaustive checkpoint regression localization;
- execution-driven bisect over recorded outputs or real CPU ONNX artifacts;
- bounded MCR 1.3 reports with stable evidence IDs, distinct volatile run IDs,
  deduplicated manifests, runtime/platform provenance, and finding-to-evidence-set
  links;
- a standalone `m2riv mcr verify` conformance boundary that rehashes reports,
  manifests, sets, plans, and known supplemental artifacts from any producer;
- explicit verifier completeness/coverage fields plus a full bundle emitted by a
  standard-library-only independent producer;
- RFC 0012 canonical identity rules with matching Python and Node golden vectors;
- artifact traversal and byte budgets that fail before unbounded hashing/parsing;
- portable JSON, Markdown, JUnit, and SARIF release outputs;
- SHA-pinned CI plus tagged wheel/sdist builds with checksums, SPDX SBOM, and
  signed GitHub provenance attestations;
- deterministic tests, strict typing, linting, and offline CI.

## Real CPU-only quantization demo

The primary demo uses real observations rather than hand-written pass/fail fixtures.
It uses scikit-learn's bundled copy of the UCI handwritten-digits dataset and a
reviewed FP32 fixture from a real sklearn MLP, exports the same fixed weights to
FP16 ONNX, creates static INT8 QDQ builds with ONNX Runtime, and runs 629 paired
holdout cases entirely on CPU. Pinning the fixture prevents BLAS-specific training
drift from changing the artifact under test.

```console
python -m pip install -e ".[onnx-demo]"
python examples/onnx_quantization/run_demo.py --output runs/onnx-quantization
```

Expected release story with seed 23:

```text
Build                                      Overall    Critical rare slice   Gate
build-00-fp16                               94.75%                91.49%   PASS
build-01-int8-balanced                94.75–94.91%          91.49–93.62%   PASS
build-02-int8-calibration-scale-065   92.85–93.16%          74.47–78.72%  BLOCK
build-03-int8-calibration-scale-060   92.37–92.85%          70.21–76.60%  BLOCK

First bad build: build-02-int8-calibration-scale-065
```

The numerical diff makes the causal chain inspectable rather than stopping at
the failing build (128 declared cases, FP16 baseline vs scale-0.65 INT8). The
generated report records the exact per-tensor max error, RMSE, and cosine values
for the executing platform instead of copying volatile runtime evidence here.

The critical slice is declared from inputs—rare training digit 1 with normalized
ink sum at least 18—not selected after seeing model failures. The complete
[reproduction procedure](examples/onnx_quantization/README.md) explains the data,
calibration mistake, policy, limitations, and generated evidence.
The displayed ranges are the bounded Linux/Windows results for byte-identical
artifacts, not tolerance around different trained models. The source fixture has
a pinned SHA-256 and is checked before execution. MCR
executions record OS, architecture, Python, framework, and framework version, and
CI preserves both Linux and Windows bundles so bounded runtime differences remain
auditable without changing the PASS/BLOCK boundary.

```console
m2riv artifact diff \
  runs/onnx-quantization/artifacts/build-00-fp16.onnx \
  runs/onnx-quantization/artifacts/build-02-int8-calibration-scale-065.onnx

m2riv artifact numerical-diff \
  runs/onnx-quantization/artifacts/build-00-fp16.onnx \
  runs/onnx-quantization/artifacts/build-02-int8-calibration-scale-065.onnx \
  --suite runs/onnx-quantization/suite.jsonl

m2riv bisect runs/onnx-quantization/checkpoints.jsonl --mode monotonic

m2riv schema export ./schemas/v1
# Exported 21 public schemas to schemas/v1

m2riv mcr verify runs/onnx-quantization/reports/build-02-int8-calibration-scale-065
# In a release gate, require every linked local component to be rehashed:
m2riv mcr verify runs/onnx-quantization/reports/build-02-int8-calibration-scale-065 --strict
```

The smaller [opset-upgrade example](examples/onnx_opset_upgrade/README.md) covers
a second artifact axis: it records an opset 17 → 18 structural change, proves all
shared tensors remain identical on the declared suite, and emits a `PASS` MCR.

To gate previously captured outputs in CI:

```console
m2riv compare baseline.jsonl candidate.jsonl \
  --suite suite.jsonl \
  --policy policy.yaml \
  --slice-key frequency \
  --output runs/release
```

The command produces the compiled plan, a deduplicated `evidence-manifest.json`,
and bounded MCR JSON, Markdown, JUnit, and SARIF. Exit code `2` means `BLOCK`;
exit code `3` means invalid or incomplete evidence; exit code `4` means a `WARN`
that the policy did not explicitly allow. `WARN` is fail-closed by default. See
the [recorded-output example](examples/recorded_compare/README.md).

An MCR has two explicit identities. `id` addresses replay-stable evidence and
excludes timestamps and run-scoped timing metrics; `run_id` addresses the exact
execution, including timing, cache provenance, timestamp, and final verdict.
The verifier accepts a bundle produced by M2RIV or another implementation; it
does not execute the model or trust prose summaries.
`integrity_valid` means every performed check passed, while
`verification_complete` means all referenced local bundle components were
recognized and rehashed. This is a self-consistency check, not a producer
signature: the result explicitly reports `authenticity_verified: false` and
`trust_scope: self-consistency-only`. See the
[independent producer](examples/independent_producer/README.md),
[full conformance bundle](examples/mcr_conformance/full), and
[content-identity vectors](examples/content_identity/README.md).

For a recorded-output gate in GitHub Actions, the repository also exposes a thin
composite action:

```yaml
- uses: actions/checkout@REPLACE_WITH_IMMUTABLE_COMMIT
  with:
    persist-credentials: false
- uses: M2RIV/m2riv@REPLACE_WITH_IMMUTABLE_COMMIT
  with:
    baseline: evidence/baseline.jsonl
    candidate: evidence/candidate.jsonl
    suite: evidence/suite.jsonl
    policy: evidence/policy.yaml
```

It installs the checked-out M2RIV revision from a hash-locked dependency export,
compares and verifies the report, uploads the bounded release bundle, and then
surfaces one fail-closed exit code. CI executes the action itself against the
recorded-output example and asserts the expected `BLOCK` result.

To compare provider-managed or self-hosted OpenAI-compatible endpoints without
putting credentials in shell history:

```console
export M2RIV_BASELINE_API_KEY=...
export M2RIV_CANDIDATE_API_KEY=...
m2riv compare-api https://baseline.example/v1 https://candidate.example/v1 \
  --baseline-model model-v1 \
  --candidate-model model-v2 \
  --baseline-revision deploy-2026-08-28 \
  --candidate-revision deploy-2026-08-29 \
  --suite suite.jsonl \
  --policy policy.yaml \
  --output runs/api-release
```

The adapter bounds attempts, response bytes, per-request time, and cumulative
elapsed time. Credentials never participate in snapshots, fingerprints, cache
entries, reports, or error messages. Remote comparisons use a run-local cache by
default, so mutable provider endpoints cannot silently reuse stale observations.
Credential-bearing requests require HTTPS, and cloud metadata link-local endpoints
are rejected. Loopback and private-network URLs remain available for self-hosted
inference without credentials.
Use the non-secret credential-scope options when endpoint routing varies by tenant.
See the [API comparison example](examples/api_compare/README.md).

To localize a regression over already evaluated checkpoints:

```console
m2riv bisect examples/checkpoint_bisect/checkpoints.jsonl --mode monotonic
```

Monotonic mode is `O(log n)`. When monotonicity is not defensible, use
`--mode sparse_audit` for a bounded survey or `--mode linear_audit` for an
exhaustive result. `WARN`, `ERROR`, and observed non-monotonicity never produce a
fabricated first-bad revision.

To execute the checkpoints selected by the bisect strategy and preserve a full
report bundle for every evaluated build:

```console
m2riv bisect-run runs/onnx-quantization/artifact-checkpoints.jsonl \
  --adapter onnx \
  --suite runs/onnx-quantization/suite.jsonl \
  --policy runs/onnx-quantization/policy.yaml \
  --slice-key risk \
  --family cv \
  --output runs/onnx-bisect
```

Artifact manifests accept only `checkpoint` and `artifact` fields. They cannot
carry commands or shell fragments. `bisect-run` compares each selected artifact
to checkpoint zero, executes it through the chosen adapter, and writes the final
boundary plus per-checkpoint MCR and evidence-manifest paths.

## Architectural bet: evidence before verdicts

Every gate decision is designed as a claim over immutable evidence, rather than a
bare score. Model snapshots, observations, statistical diffs, and reports can be
content-addressed and linked as an evidence graph. This makes release decisions
auditable, cacheable, portable across CI systems, and usable in air-gapped
environments.

Per-observation references live in a content-addressed evidence manifest. Metrics
refer to reusable evidence-set IDs, so the stable MCR envelope remains small even
when several metrics and slices reuse the same paired observations.

See [RFC-0001](rfcs/0001-project-scope.md),
[RFC-0002](rfcs/0002-core-contracts.md),
[RFC-0003](rfcs/0003-evidence-graph.md), and
[RFC-0004](rfcs/0004-purple-team-threat-model.md),
[RFC-0005](rfcs/0005-network-and-bisect-threat-model.md), and
[RFC-0006](rfcs/0006-plugin-execution-and-release-plan.md), and
[RFC-0009](rfcs/0009-bounded-evidence-and-executed-bisect.md), and
[RFC-0013](rfcs/0013-authenticated-cache-and-evidence-trust.md) for contracts,
threat models, and extension boundaries. The
[architecture note](docs/architecture.md) explains how the evidence kernel stays
independent of local, Ray, Kubernetes, and proprietary execution fabrics.
The [Plugin SDK guide](docs/plugin-sdk.md) shows how external maintainers can add
metrics and execution backends without changing release semantics.
See [ROADMAP.md](ROADMAP.md) for ecosystem milestones and
[GOVERNANCE.md](GOVERNANCE.md) for the path from contributor to maintainer.
Release-facing changes are tracked in [CHANGELOG.md](CHANGELOG.md).
Public publication is governed by the owner-side
[release checklist](docs/release-checklist.md); repository automation cannot
self-approve brand clearance, PyPI trust, or security-notification ownership.

## Development

```console
python -m pip install -e ".[dev]"
ruff check .
mypy src
pytest
```

M2RIV is pre-alpha. Public contracts use explicit schema versions, but stability
is not promised until v1.0. The M2RIV name is provisional until the public-v0.1
[brand decision gate](rfcs/0008-brand-decision-gate.md) is complete.

## License

Apache-2.0. See [LICENSE](LICENSE).
