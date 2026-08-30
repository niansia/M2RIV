# Architecture: Model Change Report, Evidence Kernel, and Pluggable Execution

Merriv separates the portable semantics of an evaluation decision from both the tool
that produced evidence and the system that consumes it. The core is intentionally
smaller than any registry, comparator, evaluation platform, or execution fabric.

```text
ModelOpt / Polygraphy / MLflow / evaluators / Merriv CLI / internal tools
                              |
                  evidence + exact provenance
                              |
             Model Change Report (portable contract)
              /               |                 \
   CI evaluation gate   consumer policy input    audit / bisect
              \               |                 /
                independent verification boundary
```

The Merriv reference implementation supplies one evidence path:

```text
adapters -> compiled plan -> executor -> observations -> paired metrics
        -> statistical policy -> Model Change Report -> conformance/verification
```

Neither path is privileged by the Model Change Report contract. A producer may use Polygraphy,
ModelOpt, an internal compiler CI, or another language as long as it satisfies the
same public schemas, identities, decision states, and evidence references.
Python adapter, executor, and metric Protocols are reference-implementation APIs,
not the report extension ABI. External systems integrate through JSON Schema,
conformance fixtures, process/file imports, in-toto Statements, or OCI artifacts.

## Evidence kernel

The kernel owns content identity, public contracts, evidence links, paired
statistics, gate semantics, and report compatibility. It never assumes a model
framework or cluster scheduler. This is where long-term stability belongs.

Deployment artifacts also have an inference-free evidence path:

```text
artifact bytes -> ArtifactProfile -> ArtifactDiff
                              |
                              +-> per-tensor NumericalDiff
                              |
                              +-> ModelSnapshot -> adapter execution -> observations
```

`ArtifactProfile` and `ArtifactDiff` do not claim behavioral impact. They expose
structural evidence before inference: hashes, ONNX opsets/operators, initializer
dtypes and element counts, graph interfaces, quantization form, external-data
presence, and known sidecar hashes. A paired run is still required to claim a
quality or systems regression.

`NumericalDiff` instruments tensors that retain the same names across both ONNX
graphs, executes them with the CPU provider, and aggregates bounded error metrics.
It reports unmatched tensors instead of inventing a correspondence. This makes
the first observed activation drift reviewable while keeping graph-matching
claims honest.

ONNX parsing and ONNX Runtime execution are optional native-code boundaries. The
inspector is bounded and does not load external tensor data; the reference runtime
adapter is CPU-only, refuses external tensor data, and never registers custom-op
libraries. Hostile artifacts still belong in an OS-isolated executor.

## Execution fabric

Adapters describe models and produce observations. Executors decide whether work
runs locally, in subprocesses, through a remote worker, or inside an external
scheduler. Cases and observations remain identical across execution fabrics, so
distributed execution can be added without changing release semantics.

## Policy compiler

The policy compiler turns human-reviewable YAML, suite slices, metric declarations,
and plugin provenance into a content-addressed plan before inference. `PASS`,
`WARN`, `INSUFFICIENT_POWER`, `BLOCK`, and `ERROR` remain separate outcomes.
The policy declares family-wise alpha, Holm-Bonferroni correction, target power,
and optional per-rule maximum MDE; insufficient evidence can never become `PASS`.

Metrics consume paired baseline/candidate observations after execution. Each metric
declares a stable ID, unit, optimization direction, and whether its samples are
binary. This prevents adapters from smuggling their own gate semantics into the
kernel and lets latency, quality, cost, safety, and hardware evidence share one
statistical/reporting path.

## Regression localization

Bisect consumes the release gate predicate over an ordered checkpoint list.
Binary search is only exact under a declared monotonicity assumption. Sparse mode
reports bounded sampled evidence, while linear audit can prove the first observed
failure and expose `BLOCK` to `PASS` reversals. `WARN`, `INSUFFICIENT_POWER`,
`ERROR`, and callback exceptions are inconclusive rather than silently coerced
to good or bad.

The execution-driven path accepts an ordered manifest of artifact paths, never
commands. Checkpoint zero is the baseline. The bisect engine chooses an index;
the configured adapter executes that artifact against the fixed suite; the normal
paired pipeline emits a gate and report bundle; and only that gate status returns
to the localization algorithm. Every evaluated point therefore has the same
evidence and failure semantics as an ordinary release comparison.

## Model Change Report protocol boundary

A Model Change Report is the portable boundary. The strategic goal is for
registries, evaluators, compiler toolchains, and CI providers to produce or
consume reports independently of the Merriv CLI. The report contract may outlive
or be implemented without this CLI.

Model Change Report schema 0.4 keeps per-observation references out of repeated metric records.
Metrics point to content-addressed `EvidenceSet` objects in an external
`EvidenceManifest`; the report contains only the manifest identity and bounded
supplemental evidence such as an artifact diff. Bundle persistence verifies every
manifest identity and set reference before atomically publishing it.

`merriv mcr verify` is the producer-neutral consumption boundary. It validates the
Model Change Report contract, recomputes stable and run identities, rehashes manifests and evidence
sets, checks all set references, and rehashes release plans plus recognized
artifact/numerical diffs when their bodies are present. Unknown or remote evidence
is surfaced as an explicit warning rather than silently treated as verified.
`--strict` promotes those warnings to an error for release gating. Verification is
deliberately labeled `self-consistency-only`: without an external producer signature
or transparency record it cannot establish who created the internally valid bundle.
Its machine-readable trust state independently reports integrity, bundle
completeness, evidence retrievability/recomputability, producer authentication,
transparency verification, independent reproduction, and deployment
authorization. Local verification always leaves the final authorization
`not-evaluated`.

`merriv conformance producer` adds normative fixed
PASS/WARN/INSUFFICIENT_POWER/BLOCK/ERROR vectors
and mandatory negative fixtures.
`merriv conformance consumer` verifies a deterministic consumer receipt and proves
that WARN/INSUFFICIENT_POWER/BLOCK/ERROR do not satisfy its fixed fail-closed
evaluation policy. These checks establish interoperability, not deployment
authorization, model safety, or vendor endorsement. The compatibility matrix records dry-run,
fixture, and live-runtime evidence separately.

The report `evidence_id` is a deterministic identity over snapshots, release plan,
stable metrics, finding evidence links, manifest, and supplemental artifacts.
The report `id` additionally binds the complete decision, preventing PASS and
BLOCK from sharing a report identity. Timestamp and run-scoped metrics such as
wall-clock latency are intentionally excluded from `evidence_id`; `run_id` covers
the complete measured execution. Findings point directly
to evidence sets, so a consumer never sees an unexplained `BLOCK`. Each execution
also carries the snapshot runtime profile, including framework/runtime version and
host platform fields when the adapter can establish them.

Target runs add a second root above individual bundles. Opaque tool-native output
is hashed before its structured interpretation, snapshot manifests bind identities
to retained ONNX/engine bytes, build provenance binds inputs and calibration
parameters, and `TargetEvidenceManifest` covers every retained target byte plus
every strict report identity. This root detects omissions and archive tampering;
producer authenticity remains an external attestation concern.

The supply-chain path wraps a Model Change Report as an in-toto predicate and can package the
unsigned Statement in an OCI 1.1 subject/referrer manifest. SLSA provenance,
SPDX/CycloneDX BOMs, and OpenSSF Model Signing/Sigstore remain referenced external
contracts. An organization policy engine combines those verified inputs and owns
the final deployment `ALLOW`/`DENY`. See
[supply-chain interoperability](supply-chain-interop.md).
