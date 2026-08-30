# Model Change Report specification candidate

Status: pre-alpha specification candidate

Current envelope: MCR 0.4.0

Identity protocol: [RFC 0012](../rfcs/0012-content-identity-canonicalization.md) and
[RFC 0015](../rfcs/0015-mcr-0.4-evidence-identity-and-target-root.md)

Normative schemas: [`schemas/mcr-0.4`](../schemas/mcr-0.4)

MCR is a vendor-neutral, language-neutral release-evidence envelope for a change
between two deployable model snapshots. Merriv is the reference implementation,
not the only permitted producer or consumer. The `mcr:` wire namespace remains
independent of the provisional Merriv product name.

## Normative producer requirements

An MCR producer MUST:

1. identify the exact baseline and candidate snapshots with content IDs;
2. emit three separate identities: replay-stable `evidence_id`, decision-bound
   report `id`, and exact execution `run_id`;
3. emit one of `PASS`, `WARN`, `INSUFFICIENT_POWER`, `BLOCK`, or `ERROR` without
   collapsing uncertainty, low power, or execution failure into `PASS`;
4. link every metric or finding that claims observation support to a resolvable
   evidence set;
5. state limitations and runtime provenance needed to interpret each claim;
6. apply RFC 0012 canonical JSON and domain-separated hashing exactly;
7. preserve opaque tool-native output when a structured claim names an external
   comparator as its oracle;
8. avoid claiming producer authenticity from content hashing alone.

MCR 0.4 calls the evaluation-policy disposition `decision.allowed`. This frozen
wire name MUST be interpreted only as “the evaluation policy bound into this
report was satisfied.” It MUST NOT be interpreted as deployment or promotion
authorization.

For identity algorithm v1, producers MUST perform schema-aware typed-contract
conversion before serialization. A generic JSON parse/stringify round trip is
not sufficient because it can erase integral-float type and negative-zero state.
The exact typed conformance vectors are normative test inputs.

## Reference statistical profile

The MCR envelope preserves intervals plus raw and adjusted p-values, but MCR
0.4.0 does not yet have structured fields for a hypothesis-test method, null,
alternative, or assumptions. A producer MUST NOT present an undocumented tail
probability as a universally interpretable p-value. Until a future envelope
version addresses that gap, producers that emit these fields MUST document the
method and assumptions in retained statistical evidence or the finding message.

The Merriv reference producer uses exact two-sided McNemar evidence for binary
paired metrics at a zero margin, Tango's matched-proportion score test and
inverted score interval for a non-zero binary margin, and a two-sided paired
sign-randomization test for continuous effects. Binary outcomes are never routed
through the continuous sign-randomization assumption. Percentile-bootstrap tail
counts are not used as formal p-values.

Every confidence interval is evaluated in full; a p-value does not replace the
interval decision. The non-zero matched-binary score interval is the confidence
set dual of its Tango test. Continuous and zero-margin binary intervals remain
paired percentile-bootstrap evidence independent of the reported
sign-randomization or exact McNemar test.

## Identity tiers

All content IDs use `mcr:sha256:<64 lowercase hexadecimal characters>`. Hash
preimages use RFC 0012 canonical JSON and the domain prefix
`mcr:<namespace>:v1\x00`.

- `evidence_id` covers replay-stable snapshots, plan, stable metrics, finding
  evidence links, evidence manifest, and supplemental evidence references. It
  intentionally excludes the final decision and volatile execution values.
- `id` covers `schema_version`, `evidence_id`, `release_plan_id`, and the complete
  decision. Two reports with the same measurements but opposite verdicts MUST
  have different `id` values.
- `run_id` covers the exact report execution, including report/evidence IDs,
  timestamp, executions, all metrics, decision, references, and limitations.

Locations such as local bundle URIs are excluded only in contracts that explicitly
define them as transport locators. Their retained byte digest remains included.

## Consumer and verifier requirements

An MCR consumer MUST:

1. validate the exact declared schema version before interpreting fields;
2. recompute every report, run, manifest, evidence-set, and recognized supplemental
   identity it relies on;
3. preserve all five decision states;
4. preserve `decision.allowed` as the bound evaluation-policy disposition and
   never translate it directly into organization deployment authorization;
5. distinguish integrity, bundle completeness, evidence-body coverage, metric
   recomputability, producer authenticity, transparency verification,
   independent reproduction, and deployment authorization;
6. reject unknown required contracts rather than guessing their semantics.

`bundle_verification_complete` means every declared local bundle component was
recognized and rehashed. `evidence_body_coverage` reports mutually exclusive
structured, opaque, unavailable, remote, redacted, and unrecognized body counts.
`metric_recomputable` is true only when the retained plan and every observation
body required by metrics were verified. None of these fields establishes who
produced the bundle.

After verification, an organization policy engine MAY combine the MCR evaluation
decision with authenticated producer identity, transparency evidence, provenance,
BOM, vulnerability, risk, and environment policy to emit its own `ALLOW` or
`DENY`. That authorization is a separate consumer-side object and is never an
MCR producer claim.

## Tool-native and target evidence

`ToolNativeEvidence` binds an opaque native output, its producer/version, media
type, runner names, purpose, and exit code. A `BackendComparisonEvidence` that
claims a comparator-native oracle MUST reference a verified tool-native body and
its structured per-case verdict MUST agree with the native exit code.

`SnapshotArtifactManifest` binds snapshot identity to actual retained artifact
bytes. `BuildProvenanceEvidence` binds source revision, builder/version, inputs,
outputs, parameters, calibration cohort, parent build, and output snapshot.
`TargetEvidenceManifest` is a target-run root over every retained file and strict
MCR bundle. It rejects changed, missing, and unlisted files. It is still a content
root, not a producer signature.

## Conformance and compatibility

The normative producer suite contains fixed `PASS`, `WARN`, `BLOCK`, and `ERROR`
vectors plus negative fixtures for tampered identity, missing evidence, unknown
version, and decision mismatch. A producer cannot claim conformance by merely
emitting self-consistent arbitrary reports.

The MCR 0.4.0 envelope is frozen for external review: fields and identity
semantics will not be edited in place. A required-field, meaning, or identity
change requires a new explicit envelope version and migration note. Consumers
select supported exact versions and fail closed on unknown versions. See the
[compatibility matrix](mcr-compatibility.md),
[conformance procedure](mcr-conformance.md),
[protocol changelog](mcr-changelog.md), and
[0.4 migration guide](mcr-0.4-migration.md).

## Trust statement

`merriv mcr verify` and `verify-target` prove bounded local self-consistency. They
do not prove authorship. A signature, trusted CI identity, transparency record, or
other external trust root is required for authenticity. Consumers MUST NOT turn a
successful content verification into an authorship, safety, or universal-release
claim.

MCR composes with existing supply-chain standards rather than replacing them.
Use SLSA for build provenance, SPDX/CycloneDX for model and component inventory,
OpenSSF Model Signing/Sigstore or enterprise PKI for producer authentication,
in-toto for the attestation Statement, OCI for artifact transport/referrer
discovery, and consumer policy for deployment authorization. See
[supply-chain interoperability](supply-chain-interop.md).
