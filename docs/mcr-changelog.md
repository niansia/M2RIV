# MCR protocol changelog

This changelog covers the portable protocol, separately from the Python package
changelog.

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
- moved normative schemas to `schemas/mcr-0.4`.

## 1.3.0 and earlier — historical pre-alpha line

The earlier experimental line introduced runtime provenance, portable bundle
verification, evidence manifests/sets, and stable-versus-run identity. Its
decision identity and provisional product-branded wire namespace were corrected
before a public 1.0 promise. See the [migration guide](mcr-0.4-migration.md).
