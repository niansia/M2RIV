# MCR protocol changelog

This changelog covers the portable protocol, separately from the Python package
changelog.

## 0.4.0 external-review freeze clarifications — 2026-08-30

The MCR envelope and identity preimages did not change:

- clarified that frozen wire field `decision.allowed` means only “evaluation
  policy satisfied” and never deployment authorization;
- moved producer/consumer conformance receipts to 0.3.0 terminology;
- moved verifier output to 0.3.0 with independent machine-readable trust
  dimensions;
- added unsigned in-toto Statement and OCI 1.1 referrer transport helpers; and
- froze MCR 0.4.0 fields and identity semantics for external review.

Verifier, conformance, importer, and OCI contracts are tooling surfaces. Their
additive revisions do not alter the MCR 0.4 report envelope.

GatePolicy 1.1.0 adds the optional prospective
`planned_difference_stddev` input. A decision-bearing `max_mde` now requires
that planned quantity; observed-design MDE remains diagnostic. This tooling
policy revision does not change the frozen MCR 0.4 report envelope or identity
preimages.

The reference producer no longer emits a centered sign-randomization test for a
matched-binary risk difference at a non-zero margin. That profile lacks the sign
symmetry assumed by the continuous test; a Holm policy now returns `ERROR` until
a dedicated paired-binary non-inferiority method is selected. This is a
statistical tooling correction, not an MCR 0.4 wire or identity change.

## 0.4.0 — 2026-08-29

Breaking pre-alpha correction:

- moved the wire namespace and hash domains from provisional product branding to
  `mcr:`;
- split replay-stable `evidence_id`, decision-bound report `id`, and exact `run_id`;
- renamed the canonical report to `mcr-report.json`;
- added explicit bundle completeness, evidence-body coverage, and metric
  recomputability verification semantics;
- added opaque tool-native evidence, snapshot byte bindings, build provenance,
  and a complete target evidence root;
- required comparator-native structured evidence to reference retained native
  output and agree with its exit code;
- added fixed ERROR and mandatory negative conformance vectors;
- added policy-family Holm-Bonferroni metadata, target power, MDE, and the
  fail-closed `INSUFFICIENT_POWER` decision;
- defined an in-toto v1 Statement schema and MCR predicate type for external
  Sigstore/cosign attestation;
- moved normative schemas to `schemas/mcr-0.4`.

## 1.3.0 and earlier — historical pre-alpha line

The earlier experimental line introduced runtime provenance, portable bundle
verification, evidence manifests/sets, and stable-versus-run identity. Its
decision identity and provisional product-branded wire namespace were corrected
before a public 1.0 promise. See the [migration guide](mcr-0.4-migration.md).
