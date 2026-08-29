# Security Policy

M2RIV is pre-alpha release-engineering software. It processes model artifacts,
evaluation inputs and outputs, policies, cache records, remote responses, and
optional plugin code. Treat all of those as sensitive and untrusted unless your
deployment establishes otherwise. Do not use M2RIV as the sole control for a
safety-critical release.

## Reporting a vulnerability

Do not open a public issue for a suspected vulnerability. Until a dedicated
security address exists, contact the repository owner privately through the
verified GitHub profile and include the affected version, reproduction steps,
impact, and any suggested mitigation. Do not include real credentials, customer
model outputs, or proprietary artifacts.

A dedicated monitored security contact and response SLA are release blockers for
public v0.1. The project does not currently promise an embargo timeline or bounty.

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
  prompts sent to it.
- Reports attest what M2RIV observed under a named policy and runtime. They do not
  prove that an artifact is safe, unbiased, or suitable for every distribution.

## Fail-closed controls

- `PASS` is the only release-allowed status by default. `WARN` requires the policy
  author to set `allow_warn: true`; `BLOCK`, execution errors, missing pairs,
  malformed inputs, and unresolved evidence are not release-allowed.
- JSONL/YAML parsing, cache envelopes, network responses, retry/time budgets,
  plugin cardinality, evidence cardinality, and execution plans are bounded.
- Artifact hashing defaults to a 16 GiB total/per-file ceiling and 100,000 traversed
  entries. ONNX parsing has a separate 512 MiB ceiling plus graph cardinality
  bounds. CLI budget flags may be reduced for CI tenants.
- Symlinks, junctions, special files, mutable files during hashing, ONNX external
  tensor data, and unregistered custom ops fail closed.
- Execution-driven bisect manifests accept only `checkpoint` and `artifact`.
  Commands and unknown fields are rejected.
- Report bundles verify content identities and evidence-set references before
  atomically publishing the MCR and its evidence manifest.

Resource limits reduce accidental and adversarial exhaustion; they are not a
replacement for OS-level CPU, memory, disk, process, and network quotas.

## Build and release supply chain

GitHub Actions dependencies are pinned to immutable commit SHAs. Weekly Dependabot
checks propose Python and action updates. Tagged builds produce a wheel, source
distribution, SHA-256 checksum file, SPDX JSON SBOM, and GitHub/Sigstore artifact
provenance. Verify a downloaded artifact with:

```console
sha256sum -c SHA256SUMS
gh attestation verify PATH/TO/ARTIFACT -R OWNER/REPOSITORY
```

PyPI publishing is intentionally disabled until the package namespace and GitHub
Trusted Publisher are configured. A generated SBOM or provenance attestation says
where an artifact came from; it is not a claim that the artifact has no
vulnerabilities.
