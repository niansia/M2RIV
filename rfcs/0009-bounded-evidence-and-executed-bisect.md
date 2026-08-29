# RFC 0009: Bounded evidence and execution-driven bisect

- Decision status: Accepted
- Implementation status: Implemented for MCR 1.1 and retained in 1.2
- Contract impact: Model Change Report 1.1

## Problem

The first MCR representation copied every per-case evidence reference into every
metric and slice. The report therefore grew with `cases × metrics`, even though
many metrics used the same observations. The original bisect command also consumed
precomputed statuses, which localized a known sequence but could not select and
execute a deployment artifact itself.

Both weaknesses sit on M2RIV's strategic boundary. A portable release envelope
must remain reviewable at industrial suite sizes, and deployment-side localization
must demonstrate that it can run quantized or compiled artifacts rather than only
restate synthetic statuses.

## Decision

MCR 1.1 replaces metric-local evidence arrays with `evidence_set_id`. A separate,
content-addressed `EvidenceManifest` stores unique `EvidenceRef` objects and
reusable ordered `EvidenceSet` membership. The MCR stores a bounded manifest
reference containing its identity and counts. Supplemental release evidence such
as an artifact diff remains bounded in the MCR.

Bundle publication recomputes the manifest identity, verifies its counts, and
rejects unknown evidence-set IDs. The manifest is published as
`evidence-manifest.json`; consumers can retrieve case evidence only when needed.

`bisect-run` accepts a strict JSONL sequence with exactly two fields:
`checkpoint` and `artifact`. Checkpoint zero is the fixed baseline. A caller-owned
adapter factory resolves each artifact; the existing bisect engine selects indices;
the ordinary paired comparison pipeline executes each selected candidate and emits
a complete report bundle. No manifest field is interpreted as a command.

## Release disposition

`WARN` is evidence of uncertainty, not permission. Policies default to
`allow_warn: false`; only an explicit policy opt-in makes a WARN release-allowed.
CI exit code 4 distinguishes a disallowed WARN from BLOCK (2) and invalid or
incomplete evidence (3).

## Resource policy

Artifact identity must be bounded before data is read or a directory is fully
materialized. Total bytes, per-file bytes, and traversal entries are independent
budgets. Files must be regular, stable while hashed, and reached without symlink
or junction traversal. Format parsers retain narrower format-specific limits.

## Consequences

- The MCR size is proportional to metrics and findings, while detailed evidence
  moves to one deduplicated manifest.
- MCR 1.0 consumers require a migration because metric-local `evidence` is removed.
- Evidence manifests may still be large and should be streamed or stored in a
  content-addressed object store by future consumers.
- Monotonic bisect remains an assumption. Sparse and linear audit modes retain
  bounded/inconclusive semantics; executing real checkpoints does not manufacture
  proof of monotonicity.
- An adapter can invoke native code, so execution-driven bisect must inherit the
  same process/container isolation policy as a normal comparison.
