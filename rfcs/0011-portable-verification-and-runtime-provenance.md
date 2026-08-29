# RFC 0011: Portable MCR verification and runtime provenance

- Decision status: Accepted
- Implementation status: Implemented; verification semantics extended by RFC 0015
- Contract impact: Historical MCR 1.3; current MCR 0.4 and MCRVerification 0.2

## Problem

An MCR consumer previously had to trust the producer's bundle-writing path.
Separately, ONNX Runtime could produce a small platform-dependent output change
without the report exposing enough host/runtime information to compare runs.

## Decision

MCR adds an optional `runtime_profile` to each baseline/candidate execution.
Adapters record framework/runtime version, operating system, architecture, Python
version, device, and dtype when those values can be established. These fields are
run provenance and participate in `run_id`; snapshot construction may also include
them when the runtime is part of the executable model state.

`m2riv mcr verify` is a producer-neutral, inference-free verifier. It validates
the strict report contract and recomputes:

1. stable `evidence_id`, decision-bound report `id`, and volatile `run_id`;
2. evidence-manifest and evidence-set identities;
3. every metric/finding set reference;
4. a present compiled release-plan identity; and
5. recognized artifact-diff and numerical-diff identities.

Remote, redacted, missing optional, or unknown supplemental bodies are never
silently promoted to verified content. Verifiable omissions produce warnings;
identity or contract mismatches fail the bundle.

MCRVerification 0.2 separates integrity, local bundle completeness, evidence-body
coverage, observation-body verification, and metric recomputability. A partial
result is machine-visible instead of inferred from warning prose. The verifier
does not fetch remote evidence or execute a model.

A locally valid
bundle reports `trust_scope: self-consistency-only` and
`authenticity_verified: false`. Recomputing unkeyed content identities proves that
the bundle is internally self-consistent; it does not prove who produced it or
whether the producer's observations were truthful. The `--strict` option makes any
completeness warning fatal, but it does not change this authenticity boundary.

## Compatibility

Legacy 1.2/1.3 bundles remain historical contracts. Current tooling emits MCR 0.4
and requires regeneration under the migration procedure in RFC 0015.
