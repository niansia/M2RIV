# RFC 0006: Explicit plugins, execution fabrics, and compiled release plans

- Decision status: Accepted
- Implementation status: Implemented for v0.1
- Target: v0.1

## Decision

M2RIV separates model adapters, paired metrics, and execution backends. Plugin code
is registered explicitly by trusted host code; core does not automatically import
entry points. Every plugin carries a strict API version and non-secret content
identity.

Before execution, policy, suite, metrics, slices, plugin provenance, runtime
profile, seed, bootstrap count, and confidence level compile to a content-addressed
release plan. Missing metrics, missing slices, direction
mismatches, duplicate ownership, unsafe identifiers, and cardinality overflow stop
before inference cost is incurred.

Executor configuration participates in cache identity. The runner validates every
returned observation independently, and the MCR records the release-plan ID plus
the actual baseline/candidate executor provenance.

## Rationale

External schedulers should remain execution fabrics underneath M2RIV, not
dependencies of its release semantics. Likewise, a third-party metric should
extend numeric evidence without gaining authority to reinterpret `PASS`, `WARN`,
`BLOCK`, or `ERROR`.

Automatic plugin loading is intentionally deferred. It creates a supply-chain and
arbitrary-code-execution boundary that cannot be made safe through a manifest
alone.

## Threats and controls

- **Descriptor spoofing:** adapter snapshots and executor descriptors are validated
  on registration; manifest/config fingerprints and capability sets must agree.
- **Post-registration mutation:** metric declarations, adapter snapshots, executor
  descriptors, and capability sets are rechecked before retrieval.
- **Cache substitution:** the full validated executor descriptor is domain-hashed
  into every observation cache key, in addition to adapter and runtime identity.
- **Secret-bearing identity:** runtime profiles reject credential/header fields;
  plugin manifests and descriptors contain only strict identifiers and digests.
- **Plan amplification:** base metrics, slice keys, slice cardinality, planned
  metrics, plugins, capabilities, and bindings have explicit limits.
- **Exception exfiltration:** third-party metric/executor declaration and execution
  failures are replaced with bounded, secret-free kernel errors.

## Compatibility

`PluginManifest`, `ExecutorDescriptor`, and `CompiledReleasePlan` are exported as
versioned JSON Schemas. Executor and metric protocol additions must remain optional
within an API minor version; required semantic changes require a new API version.

## Known limits

The in-process registry is not a sandbox. Distributed executors, signed plugin
artifacts, SBOM attestations, and process isolation remain separate implementation
layers. A hostile local process sharing cache storage still requires operating-
system isolation.
