# Supply-chain interoperability

MCR fills one narrow gap: it records what changed between two model artifacts,
which evaluation evidence was observed, and whether the evaluation policy bound
into that report was satisfied. It is not a signing format, BOM, build-provenance
format, registry, or deployment authorization system.

## Layering

| Layer | Owns | MCR behavior |
|---|---|---|
| SPDX or CycloneDX ML-BOM | Model, dataset, component, and dependency inventory | Reference the retained BOM; do not copy its graph into MCR |
| SLSA provenance | How an artifact was built | Reference the provenance attestation; retain only comparison-relevant build facts in MCR evidence |
| OpenSSF Model Signing, Sigstore, or enterprise PKI | Producer identity and signature verification | Authenticate the artifact or attestation outside the MCR content hash |
| MCR | Baseline/candidate change, paired evidence, uncertainty, and evaluation decision | Remain producer- and consumer-neutral |
| OCI 1.1 | Artifact transport, subject association, and referrer discovery | Carry an MCR in-toto Statement as a referrer artifact |
| Organization policy engine | Promotion or deployment `ALLOW`/`DENY` | Consume verified MCR plus identity, provenance, BOM, vulnerability, and business policy inputs |

The critical invariant is:

> An MCR producer reports an evidence-bound evaluation decision. It never grants
> deployment authority.

MCR 0.4 retains the wire field `decision.allowed` for compatibility. Its sole
meaning is **evaluation policy satisfied**. CLI, Markdown, SARIF, conformance,
and verification output use that unambiguous term. Deployment authorization is
reported as `not-evaluated`.

## in-toto and cosign

Emit only the predicate body when cosign will construct and sign the Statement:

```console
merriv mcr predicate runs/release > mcr.predicate.json
cosign attest --yes \
  --type https://github.com/niansia/Merriv/attestations/model-change-report/v0.1 \
  --predicate mcr.predicate.json \
  registry.example/model@sha256:...
```

Emit the complete unsigned in-toto v1 Statement when another attestor needs the
portable JSON object:

```console
merriv mcr statement runs/release \
  --subject-name registry.example/model:v42 \
  --subject-sha256 <64-hex-digest> \
  > mcr.statement.json
```

The Statement command verifies the local MCR bundle strictly before emitting.
It does not sign, contact a transparency service, or assert producer identity.

## OCI 1.1 referrer layout

OCI 1.1 image manifests provide `artifactType` and `subject`; registries expose
subject associations through the Referrers API. Build a deterministic local OCI
image layout containing the unsigned MCR Statement as one layer:

```console
merriv mcr oci-layout runs/release \
  --subject-name registry.example/model:v42 \
  --subject-digest sha256:<model-manifest-digest> \
  --subject-size <model-manifest-byte-size> \
  --output runs/release-oci
```

The layout contains:

```text
runs/release-oci/
├── oci-layout
├── index.json
└── blobs/sha256/
    ├── <empty-config>
    ├── <mcr-statement>
    └── <referrer-manifest>
```

The referrer manifest uses:

- manifest media type `application/vnd.oci.image.manifest.v1+json`;
- artifact and layer type `application/vnd.in-toto.mcr+json`;
- the standard OCI empty JSON config; and
- a `subject` descriptor supplied by digest, size, and media type.

This is a local transport prototype, not a registry client. A conforming OCI
client can copy the layout to a registry after the subject exists there. Registry
authentication, fallback tags for registries without the Referrers API, signing,
and remote retrieval verification remain client responsibilities.

The Statement embeds the MCR report, not every referenced evidence body. Remote
consumers must be able to retrieve any evidence on which their policy relies or
treat the result as incomplete.

## Machine-readable trust state

`merriv mcr verify` emits independent trust dimensions instead of letting
`valid: true` imply more than local integrity:

```json
{
  "trust": {
    "integrity_verified": true,
    "bundle_complete": true,
    "evidence_retrievable": true,
    "evidence_recomputable": true,
    "producer_authenticated": false,
    "transparency_verified": false,
    "independently_reproduced": false,
    "deployment_authorization": "not-evaluated"
  }
}
```

The local verifier cannot turn the last three `false` values into `true`. A
signature/transparency verifier or an independent reproduction receipt must add
those claims under its own authenticated contract and policy.

## References

- [in-toto Statement v1](https://github.com/in-toto/attestation/blob/main/spec/v1/statement.md)
- [in-toto envelope guidance](https://github.com/in-toto/attestation/blob/main/spec/v1/envelope.md)
- [OCI image manifest and artifact guidance](https://github.com/opencontainers/image-spec/blob/main/manifest.md)
- [OCI 1.1 artifact and Referrers overview](https://opencontainers.org/posts/blog/2024-03-13-image-and-distribution-1-1/)
- [SLSA build provenance](https://slsa.dev/spec/v1.2/build-provenance)
- [OpenSSF Model Signing](https://openssf.org/projects/model-signing/)
- [CycloneDX ML-BOM](https://cyclonedx.org/capabilities/mlbom/)
- [SPDX AI profile](https://spdx.github.io/spdx-spec/v3.0.1/model/AI/AI/)
