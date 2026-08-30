# RFC 0014: Model Change Report protocol and conformance boundary

- Status: Accepted
- Date: 2026-08-29

## Decision

Model Change Report is the project’s portable evidence object. Merriv is its
reference implementation. Deployment artifacts, compiler/runtime tools,
evaluators, registries, CI systems, and promotion controllers may produce or
consume reports without using the Merriv Python API.

The project will maintain language-neutral schemas, RFC 0012 identity vectors,
producer and consumer conformance profiles, and an explicit compatibility
matrix. Behavioral evaluation remains an external evidence source rather than a
kernel-owned evaluator catalog.

Consumer conformance requires decision preservation and a fail-closed evaluation
policy: only PASS satisfies the fixed profile; WARN, INSUFFICIENT_POWER, BLOCK,
and ERROR do not. Deployment authorization remains consumer-side. Content
verification remains distinct from producer authenticity.

## Consequences

- Core feature work is judged by protocol leverage, not evaluator count.
- Integrations live outside the four-dependency kernel whenever possible.
- Dry-run or normalized fixtures cannot be cited as live runtime evidence.
- Certification is reproducible self-attestation until neutral governance exists.
- Breaking identity or decision semantics require a new Model Change Report
  envelope version.
