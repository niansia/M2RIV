# MCR reference Rust

This crate is an independent, deliberately small MCR 0.4 producer and verifier.
It does not import or invoke the Python `m2riv` package. Its scope is the protocol
boundary, not model execution:

```console
cargo run --manifest-path reference/mcr-reference-rust/Cargo.toml -- \
  vectors examples/content_identity/golden-vectors.json
cargo run --manifest-path reference/mcr-reference-rust/Cargo.toml -- \
  float-vectors examples/content_identity/float-vectors.json
cargo run --manifest-path reference/mcr-reference-rust/Cargo.toml -- \
  produce reference/mcr-reference-rust/simple-evidence.json runs/rust-mcr
merriv mcr verify runs/rust-mcr --strict
cargo run --manifest-path reference/mcr-reference-rust/Cargo.toml -- \
  verify examples/mcr_conformance/full
```

The producer expands all MCR defaults and performs the schema-aware float
conversion required by identity algorithm v1. The verifier recomputes the stable
evidence ID, decision-bound report ID, and volatile run ID, normalizes typed UTC
datetimes, restores MCR
defaults, sorts set-valued execution capabilities, and enforces fail-closed
PASS/BLOCK semantics.

This proves two-way implementation interoperability. Because the crate still
lives in this repository, it is not evidence of external adoption or independent
governance.
