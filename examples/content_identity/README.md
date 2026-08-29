# Content-identity conformance

`golden-vectors.json` freezes 20 canonical JSON byte strings and SHA-256
fingerprints for the MCR v1 identity algorithm. The suite covers binary64
edge cases, integer/float distinction, Unicode scalar ordering, typed datetimes,
paths, sets, escaping, null/default handling, and large integers.
`float-vectors.json` adds 1,024 exact finite binary64 spellings selected from
boundary anchors and a reproducible SHA-256 sequence. The Python, Node, and Rust
verifiers do not import M2RIV.

```console
python examples/content_identity/verify_golden.py
node examples/content_identity/verify_golden.mjs
cargo run --manifest-path reference/mcr-reference-rust/Cargo.toml -- \
  vectors examples/content_identity/golden-vectors.json
cargo run --manifest-path reference/mcr-reference-rust/Cargo.toml -- \
  float-vectors examples/content_identity/float-vectors.json
```

The `$float64` vector notation stores exact IEEE-754 bits, so `1` and `1.0`
cannot collapse while crossing a generic JSON parser. It is a conformance-input
notation, not an alternate MCR wire format. The normative rules, portable
numeric profile, typed-contract conversion, and domain separation are in
[RFC 0012](../../rfcs/0012-content-identity-canonicalization.md).
