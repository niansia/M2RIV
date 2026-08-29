# MCR conformance suite

Conformance is an executable interoperability claim, not a logo or a claim that
a model is safe. The normative suite contains exact `PASS`, `WARN`, and `BLOCK`
profiles plus a full cross-language identity bundle.

## Producer profile

An implementation emits the three fixture directories. The command verifies
each MCR strictly, recomputes every available identity, checks the expected
decision, and requires complete local evidence:

```console
m2riv conformance producer examples/mcr_conformance
```

Success means the producer can emit structurally and semantically compatible
MCR 1.3 evidence for the normative profiles. It does not prove inference,
authenticity, performance, or security beyond those fixtures.

## Consumer profile

A consumer reads the same fixtures and emits a
`ConsumerConformanceReceipt`. Each observation preserves the report ID and
decision. Only PASS may set `release_authorized: true`.

```console
python integrations/mlflow_mcr/consume.py --emit-conformance-receipt \
  examples/mcr_conformance integrations/mlflow_mcr/consumer-receipt.json
m2riv conformance consumer integrations/mlflow_mcr/consumer-receipt.json \
  --fixtures examples/mcr_conformance
```

The verifier rehashes the receipt and independently verifies the referenced
fixture semantics. A consumer that maps WARN or BLOCK to authorized fails.

## Full identity profile

The standard-library-only independent producer covers report/run identity,
release plan, evidence manifest/set, artifact diff, and numerical diff without
importing M2RIV:

```console
python examples/independent_producer/generate_bundle.py --check
m2riv mcr verify examples/mcr_conformance/full --strict
node examples/content_identity/verify_golden.mjs
cargo run --manifest-path reference/mcr-reference-rust/Cargo.toml -- \
  vectors examples/content_identity/golden-vectors.json
cargo run --manifest-path reference/mcr-reference-rust/Cargo.toml -- \
  float-vectors examples/content_identity/float-vectors.json
cargo run --manifest-path reference/mcr-reference-rust/Cargo.toml -- \
  produce reference/mcr-reference-rust/simple-evidence.json runs/rust-reference
m2riv mcr verify runs/rust-reference --strict
cargo run --manifest-path reference/mcr-reference-rust/Cargo.toml -- \
  verify examples/mcr_conformance/full
```

The final four commands form the two-way Python/Rust interoperability gate.
The Rust verifier currently covers report/run identity and decision consistency;
the Python strict verifier remains the complete local-bundle verifier.

Certification policy is described in
[`mcr-certification.md`](mcr-certification.md). Until a neutral governance body
exists, results are reproducible self-attestations, not endorsements.
