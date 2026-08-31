# Merriv

[![CI](https://github.com/niansia/Merriv/actions/workflows/ci.yml/badge.svg)](https://github.com/niansia/Merriv/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache--2.0-blue.svg)](LICENSE)
[![Python 3.11–3.14](https://img.shields.io/badge/Python-3.11%E2%80%933.14-3776AB.svg)](pyproject.toml)

You quantized, compiled, or changed the runtime of a deployed model. The new
artifact builds successfully, and backend outputs still look valid. But can this
candidate actually replace the current baseline?

**Merriv turns a baseline → candidate model change into an evidence-backed
release evaluation and a portable Model Change Report (MCR).** It catches
regressions, records why a candidate passed or failed, and can localize the first
bad build before a promotion controller acts.

**Status:** Pre-alpha reference implementation · MCR 0.4 frozen for
[external review](https://github.com/niansia/Merriv/issues/18) · no claim of a
standard or external adoption · [roadmap](ROADMAP.md)

The Model Change Report is the portable evidence contract. Merriv is one
reference producer, verifier, and conformance suite.

## The production problem

Model releases cross optimizer, compiler, runtime, hardware, registry, CI, and
team boundaries. The evidence needed to approve a change often ends up split
between evaluation databases, CI artifacts, notebooks, registry metadata,
dashboards, and chat approvals. Each tool can be locally correct while the
release process still cannot answer:

- Which exact baseline and candidate artifacts were compared?
- Which evidence and policy produced the decision?
- What runtime and platform produced that evidence?
- Can another team or a future auditor verify the handoff independently?

### Who is Merriv for?

Merriv is for model optimization, inference/runtime, ML compiler, ML platform,
and release engineering teams that need to review deployable artifact changes.
Typical changes include:

- FP16 → INT8 or FP8 quantization;
- ONNX, TensorRT, OpenVINO, or internal compiler builds;
- compiler, runtime, or execution-provider upgrades;
- backend migrations and hardware-specific builds; and
- model release CI with traceable evidence handoffs.

Merriv is **not** a training framework, general experiment tracker, general model
or prompt evaluation platform, deployment controller, registry, or serving
system. It connects the release evidence those systems already produce.

### Why not just use an evaluation script?

Keep the evaluation script—it can remain the native quality oracle. Merriv adds
the portable handoff that binds:

```text
exact baseline artifact
+ exact candidate artifact
+ evaluation evidence
+ statistical policy
+ evaluation decision
+ runtime and platform context
+ optional first-bad-build evidence
= independently verifiable Model Change Report
```

The difference is not another metric calculation. It is a durable release record
that a downstream team can verify without importing the producer's evaluation
code. Merriv uses method-appropriate paired statistical tests and multiplicity
correction; assumptions and methods live in
[statistical gate semantics](docs/statistical-gating.md).

## Where Merriv fits

![Merriv system boundary](docs/images/merriv-system-boundary.svg)

An MCR records whether its bound evaluation policy was satisfied. The consuming
organization still owns deployment authorization and combines the report with
producer identity, provenance, BOM, risk, and environment policy.

See the [detailed architecture](docs/architecture.md) for the evidence kernel,
producer/consumer boundaries, and implementation extension points.

## Looking for production workflows that break MCR 0.4

The current goal is problem validation and integration evidence—not stars and
not a declaration that MCR is a standard. Merriv is looking for:

- maintainers willing to [attack MCR 0.4](https://github.com/niansia/Merriv/issues/18)
  against a real release workflow;
- teams willing to map one real baseline → candidate release into MCR;
- independently maintained MCR producers or consumers; and
- [independent hardware/runtime reproductions](https://github.com/niansia/Merriv/issues/new?template=external-reproduction.yml).

Start with the [external validation guide](docs/external-validation.md). A useful
review can conclude that the contract does not fit: missing data, excessive
producer burden, ambiguous decisions, and rejected integrations are all valuable
evidence.

## Quick start

Run the offline demo without cloning the repository:

> [!NOTE]
> This quickstart intentionally produces a `BLOCK` report. The convenience
> `demo` wrapper exits `0` after writing the demonstration; `merriv compare` and
> the GitHub Action enforce the report and return exit code `2` for `BLOCK`.

```console
uvx --python 3.13 --from merriv==0.1.0a3 merriv demo --output runs/quickstart
```

The declared rare slice regresses more sharply than the common slice. The command
writes a compiled release plan, evidence manifest, Model Change Report JSON,
Markdown, JUnit, and
SARIF. It is a synthetic behavior demo, not adoption or empirical evidence. The
command pins the published alpha instead of installing mutable `main`. See the
[full quickstart](docs/quickstart.md).

Already have retained Polygraphy results? Import them without first learning the
recorded JSONL format:

```console
merriv import polygraphy run-results.json \
  --baseline-runner onnxrt-runner \
  --candidate-runner trt-runner \
  --policy policy.yaml \
  --output runs/polygraphy-mcr
```

The importer uses Polygraphy's native comparator. `--format normalized` is a
wiring/test interchange and is explicitly labeled as non-live evidence.

> [!IMPORTANT]
> **Replay of a real historical regression:** llama.cpp issue
> [#22544](https://github.com/ggml-org/llama.cpp/issues/22544) identifies a
> first-bad commit where `--tensor-type` was ignored during quantization; merged
> PR [#22572](https://github.com/ggml-org/llama.cpp/pull/22572) fixed it. The
> [source-anchored replay](examples/historical_llamacpp_22544) returns `BLOCK` on
> the two tensor assignments published upstream. It is a replay, not a fresh 27B
> model execution or a model-quality claim.

## How Merriv complements existing tools

Merriv does not replace native tools:

| Existing capability | Keep using it for | Merriv adds |
|---|---|---|
| Model optimizers and compilers | Producing deployable artifacts | Artifact identity, retained evidence, and release semantics |
| Backend debuggers such as Polygraphy | Layer/output comparison | A portable bundle for downstream verification and policy |
| Evaluation and registry systems such as MLflow | Metrics, experiments, and lifecycle workflows | Cross-tool evidence and a producer-neutral Model Change Report boundary |
| CI and promotion controllers | Workflow execution | Fail-closed PASS/WARN/INSUFFICIENT_POWER/BLOCK/ERROR decisions with auditable inputs |

For prompts, RAG applications, or agent trajectories, use an application-evaluation
tool first. For backend or layer debugging, use the native debugger first. Merriv
starts where those results must become reviewable release evidence. The detailed
boundaries are documented in [when to use each tool](docs/competitive-landscape.md).

## Reproducible release regression

The CPU-only ONNX experiment exports one fixed model to FP16 and three real INT8
QDQ builds and evaluates 629 paired holdout cases. It intentionally changes the
calibration range, so it is a controlled regression test—not the headline proof:

> [!CAUTION]
> This is an engineering fixture. The input-declared high-ink cohort and the
> 0.55/0.50 calibration scales are deliberate deterministic negative controls
> chosen to exercise a stable cross-runner PASS/BLOCK/first-bad-build contract.
> They are not prospectively registered scientific evidence or estimates of
> real-world regression frequency or severity.

| Build | Overall (n=629) | High-ink slice (n=386) | Gate |
|---|---:|---:|---:|
| FP16 baseline | 94.8% | 95.6% | REFERENCE (self-check PASS) |
| INT8 balanced | 94.8% | 95.3% | PASS |
| INT8 scale 0.55 | 90.3% | 89.1% | BLOCK |
| INT8 scale 0.50 | 89.8% | 88.9% | BLOCK |

The critical cohort is declared from inputs as normalized ink sum at least 19;
it contains 386 independent holdout cases and is not selected from model
outcomes. With that cohort, the balanced build clears both non-inferiority rules,
both contracted-calibration builds violate the high-ink rule after Holm
correction, and localization identifies build 02 as the first bad build. The
generated report remains authoritative for its exact artifact and runtime. The
example also records ONNX semantic diff, per-tensor numerical divergence, gate
evidence, and executed bisect. The exact statistical profile is documented in
[statistical gate semantics](docs/statistical-gating.md). Run it with:

> [!NOTE]
> The retained ONNX evidence toolchain currently requires Python 3.11–3.13.
> Merriv's base package supports Python 3.14, but the `onnx-demo` extra
> intentionally does not install its older retained dependencies on 3.14.

```console
uv sync --python 3.13 --frozen --extra onnx-demo
uv run --frozen python examples/onnx_quantization/run_demo.py --output runs/onnx-quantization
```

The [NVIDIA vertical](examples/nvidia_tensorrt_vertical/README.md) exercises the
same boundary with ModelOpt, TensorRT, and Polygraphy on an RTX 4060 Laptop GPU.
Its large retained evidence is distributed as a
[GitHub Release asset](https://github.com/niansia/Merriv/releases/tag/evidence-rtx4060-20260829)
rather than stored in Git history; the repository keeps the small receipt, hashes, scripts, and
[reproducible case study](docs/release-evidence-case-study.md).

### Reproduce on your hardware

Independent reproductions across NVIDIA GPUs, TensorRT versions, operating
systems, and other deployment runtimes are welcome. If you reproduce this
release story on another system, open an
[External Reproduction report](https://github.com/niansia/Merriv/issues/new?template=external-reproduction.yml).
Repository-owned reruns are not counted as external adoption.

## Model Change Report at a glance

Version 0.4 binds:

- immutable baseline and candidate snapshot identities;
- executor, runtime, platform, and build provenance;
- paired metrics, uncertainty, sample size, and slice scope;
- the exact versioned policy and five-state evaluation decision;
- policy-wide Holm-Bonferroni correction, family-wise alpha, target power, and MDE;
- content-addressed evidence sets and supplemental evidence;
- a replay-stable `evidence_id`, decision-bound report `id`, and exact `run_id`;
- optional artifact diff, numerical diff, and first-bad-build evidence.

Any conforming producer may emit a Model Change Report without using the Merriv
CLI. A consumer can verify and consume it without importing the `merriv` Python
module:

```console
merriv conformance producer examples/mcr_conformance
merriv mcr verify examples/mcr_conformance/full --strict
```

`valid` means the performed integrity checks passed. It does **not** mean the
producer is authenticated, a transparency record was checked, an independent
party reproduced the evidence, the model is safe, or deployment is authorized.
Verification reports each trust dimension separately.

## Project map

| Area | Entry point |
|---|---|
| Quickstart and generated files | [docs/quickstart.md](docs/quickstart.md) |
| Problem discovery and external review | [docs/external-validation.md](docs/external-validation.md) |
| Architecture and extension boundaries | [docs/architecture.md](docs/architecture.md) |
| Statistical gate semantics | [docs/statistical-gating.md](docs/statistical-gating.md) |
| Model Change Report specification | [docs/mcr-specification.md](docs/mcr-specification.md) |
| Normative JSON Schemas | [schemas/mcr-0.4](schemas/mcr-0.4) |
| Producer/consumer conformance | [docs/mcr-conformance.md](docs/mcr-conformance.md) |
| External producer boundary | [docs/external-producers.md](docs/external-producers.md) |
| in-toto, OCI, SLSA, OMS, and BOM composition | [docs/supply-chain-interop.md](docs/supply-chain-interop.md) |
| Compatibility and migrations | [docs/mcr-compatibility.md](docs/mcr-compatibility.md) · [docs/mcr-0.4-migration.md](docs/mcr-0.4-migration.md) |
| Golden vectors and cross-language identity | [examples/content_identity](examples/content_identity) |
| Reference integrations | [integrations](integrations) |
| Regression corpus | [corpus](corpus) |
| Real historical replay | [llama.cpp #22544](examples/historical_llamacpp_22544) |
| Threat model and security reporting | [SECURITY.md](SECURITY.md) |
| Protocol governance and design decisions | [docs/protocol-governance.md](docs/protocol-governance.md) · [rfcs](rfcs) |
| Planned compatibility work | [ROADMAP.md](ROADMAP.md) |

The base package has four runtime dependencies: `httpx`, `pydantic`, `PyYAML`,
and `typer`. ONNX, demo, and integration toolchains remain optional.

## Trust and attestation direction

Model Change Report content IDs establish integrity, not producer identity. The integration
direction is therefore an
[in-toto Statement](https://github.com/in-toto/attestation/blob/main/spec/v1/statement.md)
predicate that can be signed with Sigstore/cosign and carried by existing artifact
attestation systems. Merriv should not invent a competing signature envelope.

> [!WARNING]
> The repository-owned `predicateType` below is prototype-only. Resolve the
> [stable namespace decision](https://github.com/niansia/Merriv/issues/17) before
> an external producer persists long-lived signed attestations. This does not
> block plain JSON MCR production, consumption, conformance, or design review.

```console
merriv mcr predicate runs/release \
  > mcr.predicate.json
cosign attest --yes \
  --type https://github.com/niansia/Merriv/attestations/model-change-report/v0.1 \
  --predicate mcr.predicate.json \
  <artifact-reference>
```

Cosign supplies the in-toto subject and Statement envelope, then signs it. Merriv
only emits the predicate body; it does not hold signing keys or claim that content
identity authenticates its producer.

For a registry-native prototype, emit a complete unsigned Statement or an OCI
1.1 subject/referrer layout:

```console
merriv mcr statement runs/release \
  --subject-name registry.example/model:v42 \
  --subject-sha256 <64-hex-digest>
merriv mcr oci-layout runs/release \
  --subject-name registry.example/model:v42 \
  --subject-digest sha256:<manifest-digest> \
  --subject-size <manifest-size> \
  --output runs/release-oci
```

See [supply-chain interoperability](docs/supply-chain-interop.md) for the exact
boundary: a Model Change Report does not replace SLSA provenance,
SPDX/CycloneDX ML-BOM, OpenSSF Model Signing/Sigstore, OCI transport, or
consumer-side deployment policy.

## Regulated release records

The immediate design-partner target is teams that already need traceable model
release records in healthcare, finance, automotive, critical infrastructure, or
other governed environments. This project is not a compliance certification.
The EU AI Act high-risk requirements now apply from 2 December 2027 for Annex III
systems and 2 August 2028 for Annex I product systems; see the
[official regulation](https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32026R1744).
The practical product claim is narrower: a Model Change Report can retain exact release evidence
that an organization's own risk, quality, and compliance process decides it needs.

## Development

```console
uv sync --frozen --extra dev --extra onnx
uv run --frozen ruff check .
uv run --frozen mypy src
uv run --frozen pytest
```

CI also checks schema drift, content-identity vectors, Rust interoperability,
reproducible builds, the composite action, cross-platform package smoke tests,
CPU ONNX evidence on Linux and Windows, dependency review, CodeQL, and OpenSSF
Scorecard signals. Version `0.1.0a3` is published on
[PyPI](https://pypi.org/project/merriv/0.1.0a3/) through Trusted Publishing; the
release workflow builds, attests, and publishes only a tag that exactly matches
the package version.

Merriv is pre-alpha. Public contracts use explicit schema versions, but stability
is not promised until v1.0. The project currently has no publicly verified
external adopter; repository-owned integrations are not counted as adoption.
The public name, Python distribution, import namespace, and CLI are all `merriv`.
See the [naming decision](docs/brand.md).

Merriv is created and currently maintained by
[Niansia](https://github.com/niansia), a Computer Science graduate from Yuan Ze
University in Taiwan.

## Contributing and security

Read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a change. Compatibility
reports and questions follow [SUPPORT.md](SUPPORT.md). Report vulnerabilities only
through the [private security advisory form](https://github.com/niansia/Merriv/security/advisories/new),
not a public issue.

## Citation

Citation metadata is available in [CITATION.cff](CITATION.cff).

## License

Apache-2.0. See [LICENSE](LICENSE).
