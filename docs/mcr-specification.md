# Model Change Report specification candidate

Status: pre-alpha specification candidate  
Current envelope: MCR 1.3.0  
Identity protocol: RFC 0012  
Normative schemas: [`schemas/v1`](../schemas/v1)

MCR is a vendor-neutral, language-neutral release-evidence envelope for a change
between two deployable model snapshots. M2RIV CLI is the reference
implementation, not the only permitted producer or consumer.

## Normative requirements

An MCR producer MUST:

1. identify the exact baseline and candidate snapshots with content IDs;
2. preserve separate deterministic evidence identity (`id`) and volatile
   execution identity (`run_id`);
3. emit one of `PASS`, `WARN`, `BLOCK`, or `ERROR` without collapsing
   uncertainty into `PASS`;
4. link every metric or finding that claims observation support to a resolvable
   evidence set;
5. state limitations and runtime provenance needed to interpret the claim;
6. apply RFC 0012 canonical JSON and domain-separated hashing exactly;
7. avoid claiming producer authenticity from content hashing alone.

For identity algorithm v1, producers MUST perform schema-aware typed-contract
conversion before serialization. A generic JSON parse/stringify round trip is
not sufficient because it can erase integral-float type and negative-zero state.
The exact typed conformance vectors are normative test inputs.

An MCR consumer MUST:

1. validate the exact declared schema version before interpreting fields;
2. recompute the report, run, manifest, evidence-set, and recognized supplemental
   identities it relies on;
3. preserve all four decision states;
4. treat `WARN`, `BLOCK`, and `ERROR` as not release-authorized unless an explicit,
   separately audited policy says otherwise;
5. distinguish self-consistency, completeness, authenticity, and authorization;
6. reject unknown required contracts rather than guessing their semantics.

The JSON schemas define structural requirements. RFC 0012 defines canonical
identity. The conformance suite defines interoperability behavior. All three are
normative; prose summaries and Markdown rendering are informative.

## Trust statement

`m2riv mcr verify` proves bounded local self-consistency. It does not prove who
created the evidence. A signature, transparency log, trusted CI identity, or
other external trust root is required for authenticity. Consumers must not turn
`valid: true` into an authorship claim.

## Compatibility

MCR uses semantic versioning at the envelope boundary:

- patch: clarification or schema-compatible correction;
- minor: additive optional capability;
- major: incompatible identity or decision semantics.

Consumers should select a supported exact schema version. No pre-1.0 stability
promise is implied. See the [compatibility matrix](mcr-compatibility.md) and
[conformance procedure](mcr-conformance.md).
