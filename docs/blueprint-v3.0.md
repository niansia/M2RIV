# M2RIV Blueprint v3.0

## Protocol-first release evidence for deployable AI models

Status: working strategy, 2026-08-29

Supersedes: v2.1 product positioning; historical implementation evidence remains valid

## Thesis

Deployable model changes should cross tool and organizational boundaries with a
standardized, portable, content-addressed, verifiable evidence object. That
object is the Model Change Report (MCR). M2RIV is the reference implementation
and conformance suite.

The project is not trying to become the largest evaluation framework. Its wedge
is deployment artifact release engineering: quantization, compilation,
conversion, opset, runtime/provider, precision, tactic, and hardware changes.
Behavioral evaluators, ModelOpt, Polygraphy, MLflow, registries, CI systems, and
internal compiler tools should become MCR producers or consumers rather than
features reimplemented in core.

## Abstraction to own

MCR standardizes:

- baseline/candidate artifact identity and exact runtime provenance;
- evidence-set references and bounded supplemental artifacts;
- paired metric direction, uncertainty, scope, and sample size;
- PASS/WARN/BLOCK/ERROR release semantics;
- deterministic evidence identity versus volatile run identity;
- verification completeness versus producer authenticity;
- ordered-build regression localization references.

The success condition is not that every user runs `m2riv compare`. It is that a
tool may produce or consume MCR without M2RIV Python, while organizations still
share the same release-evidence semantics.

## System boundary

```text
ModelOpt / Polygraphy / compiler CI / evaluators / M2RIV reference CLI
                               |
                    exact retained evidence
                               |
                    MCR protocol candidate
               /               |                \
          MLflow          CI / GitHub       registry / KServe
               \               |                /
                 conformance + verification
```

M2RIV does not replace the producer's native oracle. Polygraphy still decides
whether backend outputs match under its declared comparator. MLflow still tracks
experiments and validates its own evaluation results. ModelOpt still produces
optimized checkpoints. MCR carries exact evidence into release policy,
promotion, audit, and bisect.

## Six-month focus

### Evidence already recorded

The first live target vertical now executes PyTorch-derived ONNX plus three
ModelOpt INT8 builds through ONNX Runtime and TensorRT on an RTX 4060 Laptop GPU.
Polygraphy matched all 629 outputs for every build under the declared tolerance;
the quality gate returned PASS, PASS, BLOCK, BLOCK and localized build 02. This
closes the repository-owned reference milestone, not the independent-adoption
milestone. Exact numbers and limitations live in the technical report and the
target receipt.

### 1. MCR specification and conformance

Maintain language-neutral schemas, RFC 0012 identity, producer/consumer profiles,
a compatibility matrix, and reproducible self-certification. Recruit two
independent implementations before proposing neutral governance.

### 2. NVIDIA/compiler artifact vertical

Retain an exact PyTorch/ONNX source revision, ModelOpt or declared quantization
configuration, TensorRT engine bytes, Polygraphy comparison output, GPU/software
cohort, latency boundary, VRAM measurement, task-quality evidence, gate, and
first-bad build. A skipped GPU preflight is ERROR, never PASS.

### 3. Third-party adoption

Work with three design partners: LLM inference, CV/edge, and compiler/runtime.
The deliverable is a retained CI gate bundle and feedback on MCR semantics, not a
logo or a star. Repository-owned integrations do not count as external adoption.

## Product priorities

1. Protocol correctness and cross-language identity.
2. External producer/consumer experience.
3. Real artifact-chain evidence and regression corpus.
4. Security, provenance, bounded verification, and supply-chain integrity.
5. Reference CLI ergonomics.

New evaluators, dashboards, benchmark catalogs, model registries, training
features, and cluster schedulers are explicit non-goals.

## Evidence ladder

Claims must match retained evidence:

| Level | Claim allowed |
|---|---|
| Contract/unit | Parser or schema behavior only |
| Normalized fixture | Integration wiring only |
| Exact local execution | That artifact/runtime/case cohort only |
| Target GPU execution | Compatibility on the recorded hardware/software cohort |
| Repeated performance + quality | Bounded performance claim with declared timing boundary |
| Independent reproduction | Portability across the second recorded cohort |

No later level erases the need for exact lower-level provenance.

## Moat and falsification

The moat hypothesis is that organizations need portable cross-tool release
evidence, not another score dashboard. The hypothesis is weakened if adjacent
tools converge on a widely adopted equivalent contract, or if design partners
prefer vendor-native reports and reject portable promotion semantics. The
project will publish these negative signals rather than expand scope to hide them.

## North-star metrics

- external MCR producers and consumers;
- active organizations retaining MCR gate runs;
- independently reproduced regression cases;
- adjacent-tool issues/PRs requesting MCR;
- third-party `m2riv-*` integrations maintained by people unknown to the founder.

Stars and downloads are useful reach measures, not category-ownership measures.

## Release gates

Public v0.1 still requires brand clearance, repository security controls, tagged
artifact provenance, schema drift checks, conformance fixtures, and an honest
compatibility matrix. The name may change; the `m2riv:sha256:` protocol namespace
requires an explicit migration decision before a rename.
