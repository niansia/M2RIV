# Merriv

[![CI](https://github.com/niansia/Merriv/actions/workflows/ci.yml/badge.svg)](https://github.com/niansia/Merriv/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache--2.0-blue.svg)](LICENSE)
[![Python 3.11–3.13](https://img.shields.io/badge/Python-3.11%E2%80%933.13-3776AB.svg)](pyproject.toml)

**Model release evidence you can verify.**
Pronounced **“MEH-riv”**—one word, two syllables.

An optimized model can match backend outputs and still become a worse release.
Merriv catches the regression, records the evidence, and identifies the first bad
build before a promotion controller acts.

Merriv is the **vendor-neutral release-evidence layer for deployable AI models**.
It turns a change between model builds into a portable, content-addressed, and
independently checkable **Model Change Report**.

> Model Change Report is the portable evidence contract. Merriv is its reference
> implementation.

**Status:** Pre-alpha reference implementation · seeking three external release
pilots, not claiming a standard or external adoption · [roadmap](ROADMAP.md)

![Merriv release-evidence flow](docs/images/merriv-release-evidence-flow.svg)

Named products in the diagram are interoperability examples, not bundled
dependencies or endorsements. Verification covers declared integrity and
conformance; it does not establish producer identity. The diagram has an
[editable draw.io source](docs/images/source/merriv-release-evidence-flow.drawio).

> [!IMPORTANT]
> **Real historical regression:** llama.cpp issue
> [#22544](https://github.com/ggml-org/llama.cpp/issues/22544) identifies a
> first-bad commit where `--tensor-type` was ignored during quantization; merged
> PR [#22572](https://github.com/ggml-org/llama.cpp/pull/22572) fixed it. The
> [source-anchored replay](examples/historical_llamacpp_22544) returns `BLOCK` on
> the two tensor assignments published upstream. It is a replay, not a fresh 27B
> model execution or a model-quality claim.

## Quick start

Run the offline demo without cloning the repository:

> [!NOTE]
> This quickstart intentionally produces `BLOCK` and exits with code `2`.
> That is the expected successful demonstration of the release gate.

```console
uvx --python 3.13 --from git+https://github.com/niansia/Merriv.git merriv demo --output runs/quickstart
```

The declared rare slice regresses more sharply than the common slice. The command
writes a compiled release plan, evidence manifest, Model Change Report JSON,
Markdown, JUnit, and
SARIF. It is a synthetic behavior demo, not adoption or empirical evidence. A
tagged PyPI release will shorten this to `uvx --from m2riv merriv demo`; until
then the Git URL keeps the no-clone path honest. See the
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

## Why this exists

Model builds cross optimizer, compiler, runtime, hardware, registry, and CI
boundaries. Each tool may produce a correct local answer while the release still
lacks one portable object that binds the exact artifacts, evidence, statistics,
policy, decision, and regression onset.

Merriv does not replace native tools:

| Existing capability | Keep using it for | Merriv adds |
|---|---|---|
| Model optimizers and compilers | Producing deployable artifacts | Artifact identity, retained evidence, and release semantics |
| Backend debuggers such as Polygraphy | Layer/output comparison | A portable bundle for downstream verification and policy |
| Evaluation and registry systems such as MLflow | Metrics, experiments, and lifecycle workflows | Cross-tool evidence and a producer-neutral Model Change Report boundary |
| CI and promotion controllers | Workflow execution | Fail-closed PASS/WARN/INSUFFICIENT_POWER/BLOCK/ERROR decisions with auditable inputs |

Those are **evaluation decisions**, not deployment authority. A Model Change
Report says whether its bound evaluation policy was satisfied. The consuming
organization combines the verified report, producer identity, provenance, BOM,
risk, and environment policy
to make its separate `ALLOW`/`DENY` decision.

For prompts, RAG applications, or agent trajectories, use an application-evaluation
tool first. For backend or layer debugging, use the native debugger first. Merriv
starts where those results must become reviewable release evidence. The detailed
boundaries are documented in [when to use each tool](docs/competitive-landscape.md).

## Reproducible release regression

The CPU-only ONNX experiment exports one fixed model to FP16 and three real INT8
QDQ builds and evaluates 629 paired holdout cases. It intentionally changes the
calibration range, so it is a controlled regression test—not the headline proof:

| Build | Overall (n=629) | Critical slice (n=47) | Gate |
|---|---:|---:|---:|
| FP16 baseline | 94.8% | 91.5% | PASS |
| INT8 balanced | 94.8–94.9% | 91.5–93.6% | PASS |
| INT8 scale 0.65 | 92.9–93.2% | 74.5–78.7% | WARN–BLOCK |
| INT8 scale 0.60 | 92.4–92.9% | 70.2–76.6% | BLOCK |

For the retained NVIDIA scale-0.65 run, the critical-slice paired change is
`-12.77` percentage points with a raw 95% percentile-bootstrap CI of
`[-23.40, -4.26]` points (`n=47`). That width is why reports now expose sample
size, CI level, family-wise alpha, Holm-adjusted evidence, target power, and MDE.
Its archived report predates multiplicity correction; the current two-rule Holm
family classifies the same 43/47 to 37/47 outcomes as `WARN`, not `BLOCK`.

Scale 0.65 always fails closed, but its Holm-adjusted interval is platform
dependent: some kernels produce `WARN`, others `BLOCK`. Scale 0.60 is the first
cross-platform conclusive `BLOCK`; localization reports build 02 only when its
evidence is decisive, otherwise it retains the build 01–03 uncertainty interval.
The example also records ONNX semantic diff, per-tensor numerical divergence,
gate evidence, and executed bisect. Run it with:

```console
python -m pip install -e ".[onnx-demo]"
python examples/onnx_quantization/run_demo.py --output runs/onnx-quantization
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
CLI. A consumer can verify and consume it without importing the `m2riv` Python
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
reproducible builds, the composite action, CPU ONNX evidence on Linux and Windows,
dependency review, CodeQL, and OpenSSF Scorecard signals. The release workflow
already builds, attests, and uses PyPI Trusted Publishing; the remaining external
step is registering the project/publisher and cutting the first brand-cleared tag.

Merriv is pre-alpha. Public contracts use explicit schema versions, but stability
is not promised until v1.0. The project currently has no publicly verified
external adopter; repository-owned integrations are not counted as adoption.
The public name is fixed as Merriv; the distribution/module and compatibility
CLI remain `m2riv`. See the [naming decision](docs/brand.md).

## Contributing and security

Read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a change. Compatibility
reports and questions follow [SUPPORT.md](SUPPORT.md). Report vulnerabilities only
through the [private security advisory form](https://github.com/niansia/Merriv/security/advisories/new),
not a public issue.

## Citation

Citation metadata is available in [CITATION.cff](CITATION.cff).

## License

Apache-2.0. See [LICENSE](LICENSE).
