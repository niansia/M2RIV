# MCR protocol governance

MCR is a pre-alpha protocol candidate. This document makes the compatibility
process reviewable before neutral governance exists.

## Change classes

- Editorial clarification: no schema, identity, decision, or verifier change.
- Additive capability: optional contract field or independently ignorable evidence
  type; requires schema, fixtures, compatibility entry, and changelog.
- Breaking change: identity preimage, required field, decision semantics, canonical
  filename/media type, or fail-closed behavior; requires an RFC, migration guide,
  new exact envelope version, negative tests, and cross-language vectors.
- Security correction: may use private review and embargo, but must eventually
  document the affected invariant and regression coverage.

## Review process

Breaking public changes remain open for at least seven calendar days after a
complete RFC and migration patch, unless delaying a security fix would increase
risk. The maintainer records unresolved objections and a disposition. A release
cannot claim compatibility until schemas, four-state and negative conformance,
Python/Node/Rust identity gates, and the compatibility matrix agree.

Vendor-specific requests do not receive kernel privileges. An extension belongs
outside the protocol when it can be represented as opaque/structured evidence
without changing common identity, gate, or trust semantics.

## Neutral-governance trigger

The project will propose a separate protocol working group when there are at
least two independent producers, two independent consumers, and maintainers from
more than one organization. Until then, conformance is reproducible
self-attestation and M2RIV remains the reference implementation—not a standards
body.
