# Security Policy

Merriv is pre-alpha release-engineering software. It processes model artifacts,
evaluation inputs and outputs, policies, cache records, remote responses, and
optional plugin code. Treat all of those as sensitive and untrusted unless your
deployment establishes otherwise. Do not use Merriv as the sole control for a
safety-critical release.

## Reporting a vulnerability

Do not open a public issue for a suspected vulnerability. Submit a
[private security advisory](https://github.com/niansia/Merriv/security/advisories/new)
for this repository. If that control is unavailable, contact the repository owner
privately through the [verified GitHub profile](https://github.com/niansia) and
include the affected version, reproduction steps, impact, and any suggested
mitigation. Do not include real credentials, customer model outputs, or
proprietary artifacts.

The response target is acknowledgement within 72 hours and an initial severity
assessment within seven calendar days. Remediation and disclosure timing depend
on impact and coordination needs; the project does not currently offer a bounty.
Enabling private vulnerability reporting and confirming that it is monitored are
owner-side release checklist items before public v0.1.

## Trust boundaries

- JSONL suites, policies, checkpoint manifests, cache entries, and model artifacts
  are data, not authority. They must not cause shell execution or plugin imports.
- Python plugins and in-process executors are trusted code. The SDK validates their
  declared identity and outputs; it is not a sandbox. Run third-party plugins in a
  restricted worker with network and filesystem isolation.
- ONNX parsing and ONNX Runtime cross a native-code boundary. External tensor data
  and custom-op libraries are refused by the reference adapter, but hostile models
  should still be parsed and executed inside an OS/container sandbox.
- OpenAI-compatible endpoints are external systems. Credentials are supplied at
  runtime and excluded from snapshots, cache keys, reports, and error messages.
  A redaction control is not proof that an arbitrary endpoint cannot exfiltrate
  prompts sent to it. Credential-bearing requests require HTTPS; cloud metadata
  hostnames, link-local addresses, and known non-link-local metadata addresses
  are refused. Private and loopback endpoints remain valid
  for self-hosted inference when no credential is sent.
- Cache envelopes are HMAC-authenticated. With no configuration the HMAC key is
  random and process-local, so a new process treats old entries as misses. Set a
  secret `MERRIV_CACHE_KEY` of at least 32 bytes only when deliberate cross-run or
  multi-worker reuse is required. Anyone who can read that key can forge entries;
  do not place it in reports, logs, command lines, or repository variables.
- Reports attest what Merriv observed under a named policy and runtime. They do not
  prove that an artifact is safe, unbiased, or suitable for every distribution.
  `merriv mcr verify` proves contract validity and content self-consistency only.
  Its machine-readable result therefore reports `authenticity_verified: false`
  and `trust_scope: self-consistency-only`; producer signatures are not yet part
  of the Model Change Report contract. Use `--strict` for a release gate so omitted linked local
  evidence is an error rather than a warning.

## Fail-closed controls

- `PASS` is the only status that satisfies the default evaluation policy. `WARN`
  requires the policy author to set `allow_warn: true`; `INSUFFICIENT_POWER`,
  `BLOCK`, execution errors, missing pairs, malformed inputs, and unresolved
  evidence do not satisfy it. Deployment authorization remains consumer-side.
- JSONL/YAML parsing, cache envelopes, network responses, retry/time budgets,
  plugin cardinality, evidence cardinality, and execution plans are bounded.
- JSON rejects duplicate keys, non-finite numbers, excessive nesting, and invalid
  Unicode scalar values. YAML rejects duplicate keys, aliases above the limit,
  unsafe tags, excessive nesting, and parser recursion failures. Report-visible
  case IDs reject controls, bidi overrides, surrounding whitespace, and excess
  length.
- Artifact hashing defaults to a 16 GiB total/per-file ceiling and 100,000 traversed
  entries. ONNX parsing has a separate 512 MiB ceiling plus graph cardinality
  bounds. CLI budget flags may be reduced for CI tenants.
- Symlinks, junctions, special files, mutable files during hashing, ONNX external
  tensor data, and unregistered custom ops fail closed.
- Execution-driven bisect manifests accept only `checkpoint` and `artifact`.
  Commands and unknown fields are rejected.
- Report bundles verify content identities and evidence-set references before
  atomically publishing the Model Change Report and its evidence manifest. Report paths, local
  evidence references, and ONNX inputs are read or written without following
  symbolic links or Windows reparse points; inspected ONNX bytes are the bytes
  subsequently parsed or executed.

Resource limits reduce accidental and adversarial exhaustion; they are not a
replacement for OS-level CPU, memory, disk, process, and network quotas.

## Build and release supply chain

GitHub Actions dependencies are pinned to immutable commit SHAs. Weekly Dependabot
checks propose Python and action updates, and CI audits installed Python packages
against the Python Packaging Advisory Database. Tagged builds produce a wheel, source
distribution, SHA-256 checksum file, SPDX JSON SBOM, and GitHub/Sigstore artifact
provenance. Untrusted package build steps run without an OIDC token; the separate
attestation job receives only the completed inert artifacts. Verify a download with:

```console
sha256sum -c SHA256SUMS
gh attestation verify PATH/TO/ARTIFACT -R OWNER/REPOSITORY
```

PyPI publishing is intentionally disabled until the package namespace and GitHub
Trusted Publisher are configured and the explicit brand-clearance variable is set.
The guarded workflow and remaining account-side steps are documented in the
[public release checklist](docs/release-checklist.md). A generated SBOM or
provenance attestation says where an artifact came from; it is not a claim that
the artifact has no vulnerabilities.
