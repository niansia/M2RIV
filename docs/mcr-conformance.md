# MCR conformance suite

Conformance is an executable interoperability claim, not a logo, authenticity
claim, or proof that a model is safe. MCR 0.4 replaces arbitrary self-consistent
fixtures with fixed semantic/content vectors and mandatory rejection tests.

## Producer profile

The normative suite contains exact `PASS`, `WARN`, `INSUFFICIENT_POWER`, `BLOCK`,
and `ERROR` reports.
The command verifies each fixture strictly, recomputes report/evidence/run IDs,
compares the entire normalized report to the fixed vector, and requires all five
decision states:

```console
merriv conformance producer examples/mcr_conformance
```

The same profile MUST reject four negative fixtures:

- `tampered-id`: content changed without the corresponding identity;
- `missing-evidence`: a required body is absent;
- `unknown-version`: the envelope version is unsupported;
- `decision-mismatch`: the decision no longer matches the normative vector.

Success means the producer interoperates with the exercised MCR 0.4 profile. It
does not prove inference, producer identity, security beyond the fixtures, or live
execution against an external runtime.

## Consumer profile

A consumer reads all five normative fixtures and emits a deterministic
`ConsumerConformanceReceipt`. Every observation preserves profile, report ID,
evidence ID, decision, and whether the fixed fail-closed evaluation policy is
satisfied. Only PASS satisfies that conformance policy; the receipt never
authorizes deployment.

```console
python integrations/mlflow_mcr/consume.py --emit-conformance-receipt \
  examples/mcr_conformance integrations/mlflow_mcr/consumer-receipt.json
merriv conformance consumer integrations/mlflow_mcr/consumer-receipt.json \
  --fixtures examples/mcr_conformance
```

The verifier rehashes the receipt and independently verifies the referenced
fixture semantics. A consumer that marks WARN, INSUFFICIENT_POWER, BLOCK, or
ERROR as satisfying the fixed conformance policy fails.

## Full identity and cross-language profile

The standard-library-only independent producer covers report/evidence/run
identity, release plan, evidence manifest/set, artifact diff, and numerical diff
without importing Merriv:

```console
python examples/independent_producer/generate_bundle.py --check
merriv mcr verify examples/mcr_conformance/full --strict
node examples/content_identity/verify_golden.mjs
cargo run --manifest-path reference/mcr-reference-rust/Cargo.toml -- \
  vectors examples/content_identity/golden-vectors.json
cargo run --manifest-path reference/mcr-reference-rust/Cargo.toml -- \
  float-vectors examples/content_identity/float-vectors.json
cargo run --manifest-path reference/mcr-reference-rust/Cargo.toml -- \
  produce reference/mcr-reference-rust/simple-evidence.json runs/rust-reference
merriv mcr verify runs/rust-reference --strict
cargo run --manifest-path reference/mcr-reference-rust/Cargo.toml -- \
  verify examples/mcr_conformance/full
```

The Rust verifier covers report/evidence/run identity and decision consistency;
the Python strict verifier remains the complete local-bundle verifier.
Certification policy is described in
[`mcr-certification.md`](mcr-certification.md). Until neutral governance exists,
results are reproducible self-attestations, not endorsements.
