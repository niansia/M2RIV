# RFC 0011: Portable MCR verification and runtime provenance

- Decision status: Accepted
- Implementation status: Implemented for MCR 1.3
- Contract impact: Model Change Report 1.3; MCRVerification 1.1

## Problem

An MCR consumer previously had to trust the producer's bundle-writing path.
Separately, ONNX Runtime could produce a small platform-dependent output change
without the report exposing enough host/runtime information to compare runs.

## Decision

MCR 1.3 adds an optional `runtime_profile` to each baseline/candidate execution.
Adapters record framework/runtime version, operating system, architecture, Python
version, device, and dtype when those values can be established. These fields are
run provenance and participate in `run_id`; snapshot construction may also include
them when the runtime is part of the executable model state.

`m2riv mcr verify` is a producer-neutral, inference-free verifier. It validates
the strict report contract and recomputes:

1. stable evidence `id` and volatile `run_id`;
2. evidence-manifest and evidence-set identities;
3. every metric/finding set reference;
4. a present compiled release-plan identity; and
5. recognized artifact-diff and numerical-diff identities.

Remote, redacted, missing optional, or unknown supplemental bodies are never
silently promoted to verified content. Verifiable omissions produce warnings;
identity or contract mismatches fail the bundle.

MCRVerification 1.1 separates integrity from completeness. `integrity_valid`
states that every check actually performed succeeded; `verification_complete`
states that the report and every referenced local bundle component were rehashed
without warnings. Verified and unverified supplemental-evidence counts make a
partial result machine-visible instead of requiring consumers to infer it from
warning prose. The verification scope is explicitly `report-and-local-bundle`;
the verifier does not fetch remote evidence or execute a model.

## Compatibility

The runtime profile field is optional, so an MCR 1.2 producer can migrate without
inventing provenance. The schema minor version changes because strict consumers
must explicitly accept the new execution field. MCR 1.2 remains a historical
contract; the current CLI emits MCR 1.3.
