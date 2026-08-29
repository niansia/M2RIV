# RFC-0004: Purple-Team Threat Model and Fail-Closed Release Gates

- Decision status: Accepted
- Implementation status: Implemented for v0.1
- Target: v0.1

## Purpose

M2RIV may influence whether a model reaches users. A false PASS is therefore more
dangerous than a failed or delayed run. This RFC defines the trust boundary between
untrusted adapters and artifacts, the evidence kernel, caches, statistical analysis,
policy gates, and reports.

Schema validation establishes shape, not truth. A syntactically valid content ID,
observation, claim, or plugin record is untrusted until the kernel independently
recomputes and verifies it.

## Protected properties

1. A PASS refers to the exact model artifacts, execution configuration, suite, cases,
   policy, and evidence named by the report.
2. Cached evidence cannot be substituted across snapshots, cases, attempts, plugins,
   policy versions, or incompatible runtime capabilities.
3. Missing, malformed, non-finite, non-deterministic, or unverifiable evidence never
   silently improves a verdict.
4. Reports cannot claim a stronger conclusion than the linked evidence supports.
5. Retention and redaction choices do not leak prompts, outputs, credentials, or model
   internals through reports, traces, manifests, logs, or cache metadata.

## Adversaries and failures

The design assumes artifacts and adapters may be buggy or malicious; files may change
while being inspected; workers may be interrupted; plugins may over-declare
capabilities; and users may accidentally place secrets in inputs or environment data.
It does not assume a fully compromised kernel process or operating-system root can be
made trustworthy without external signing and isolation.

## P0: must fail closed before a production gate

### Evidence verification

The kernel, never the adapter, owns observation identity. Before persistence it MUST:

- require exactly one result for every requested `(snapshot, case, attempt)` and reject
  missing, duplicate, unexpected, or reordered results;
- require returned `snapshot_id`, `case_id`, attempt, and seed to match the dispatch;
- recompute the output digest from canonical retained output when output is present;
- recompute the observation ID from its versioned identity projection;
- reject NaN, positive/negative Infinity, invalid timestamps, and unknown fields;
- record adapter/plugin version and capability negotiation in the run manifest.

Timeout, crash, parse failure, unsupported capability, empty critical slice, or any
verification failure produces ERROR/INCONCLUSIVE, never PASS. Partial evidence may be
reported diagnostically but MUST NOT satisfy a required gate.

### Cache integrity

A cache key MUST include schema and canonicalization versions, snapshot ID, suite and
case fingerprints, attempt/seed, execution profile, adapter/plugin identity, and the
evidence-access level. A cache hit MUST re-hash the stored envelope and verify all
embedded IDs before use. Writes use a temporary object plus atomic publish; incomplete
objects are ignored. Shared caches require authenticated writers or signed envelopes.

Artifacts are regular files or directories only. Symlinks, junctions, devices, sockets,
and pipes are rejected. File identity and metadata are checked around streaming hashes
to detect common time-of-check/time-of-use mutation. Production callers SHOULD hash an
immutable staged copy or read-only content-addressed store because a mutable directory
cannot be made atomic by traversal alone.

### Statistical safety

Analysis MUST preserve pairing, keep failures in the denominator, and distinguish
missingness from a zero effect. Gates MUST use uncertainty bounds rather than point
estimates where configured, enforce minimum sample sizes, correct or budget multiple
comparisons, and predeclare metric direction. Non-deterministic profiles require
repetitions and seed-level evidence; determinism claims require an explicit replay
check. No samples or no valid bootstrap replicates is INCONCLUSIVE, not PASS.

### Claim strength

Contract construction alone does not authorize claim strength. A verifier MUST enforce
an allowlist mapping from claim type and strength to evidence kinds and analysis
methods. In particular, paired observational comparisons do not establish causality.
CAUSAL requires a registered intervention/design and its assumptions; otherwise the
claim is rejected or downgraded with visible limitations. A report renderer cannot
upgrade the verified claim.

## P1: required for enterprise adoption

- Sign run manifests and evidence roots; publish verification commands and signature
  status in the Model Change Report.
- Run adapters/plugins with least privilege, network disabled by default, resource
  limits, and an explicit filesystem allowlist.
- Redact before persistence. `hash_only` observations contain neither output nor traces.
  Redaction is policy-versioned and tested against structured and free-text secrets.
- Treat manifest environment capture as an allowlist of non-secret facts. Never copy the
  process environment wholesale; scrub command lines, URIs, exception text, and logs.
- Record hardware, driver, framework, kernel/compiler, tokenizer/preprocessor, locale,
  and container image identities when relevant to reproducibility.
- Separate policy author, model submitter, evaluator, and cache-writer permissions in
  high-assurance deployments; retain an append-only audit trail.
- Use resource ceilings for decompression, tensor parsing, output size, case count, and
  trace volume to prevent denial of service and report injection.

## P2: hardening and ecosystem controls

- Transparency-log anchoring for signed Model Change Reports and revocations.
- Reproducible plugin builds, SBOM/provenance attestations, and trust tiers for third-
  party adapters.
- Differential replay across independent workers/backends to detect compromised or
  backend-specific evidence.
- Unicode normalization and confusable warnings for case IDs, slice names, labels, and
  report-visible identifiers.
- Fuzzing of canonicalization, schema migrations, corrupted caches, adapters, and report
  renderers across supported Python and operating-system versions.

## Verdict lattice

Verdicts are ordered by information, not optimism:

```text
ERROR / INCONCLUSIVE --(all required evidence verified)--> PASS or FAIL
```

FAIL cannot be converted to PASS by dropping a failed case, slice, metric, attempt, or
plugin result. Policy composition is deny-overrides for required checks: every required
gate must PASS, any FAIL yields FAIL, and any ERROR/INCONCLUSIVE yields a non-PASS final
verdict. Overrides are explicit, signed, expiring governance events rather than mutated
evidence.

## Current v0.1 posture

Implemented now: domain-separated canonical fingerprints; strict immutable contracts;
strict duplicate-key/non-finite/depth-bounded JSON and YAML; finite non-negative
latency; hash-only plaintext prohibition; kernel-owned observation identity and
adapter-output verification; authenticated atomic cache envelopes; streaming artifact
hashing; link/special-file rejection; mutation checks around file hashing and ONNX
reads; bounded response handling; and path-safe report publication and verification.

The default cache key is run-local. Deliberate shared-cache reuse requires an
operator-provided HMAC key and protected cache-writer boundary; cache authentication
does not make a compromised evaluator process trustworthy. The standalone MCR verifier
proves self-consistency only and states that authenticity is unverified.

Not yet security-complete: claim-strength verification, producer/report signatures,
adapter/plugin sandboxing, atomic directory snapshot isolation, transparency logging,
and the full statistical fail-closed rules above. Until those land, M2RIV output MUST
NOT be presented as a cryptographically attested production release decision.
